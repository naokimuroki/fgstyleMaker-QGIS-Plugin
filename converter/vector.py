# -*- coding: utf-8 -*-
"""ベクタレイヤ（点・線・面）のレンダラ → .fgstyle 変換。"""

import re

from .defaults import default_style
from .expressions import parse_condition, plain_field_name
from . import mlexpr
from .symbols import props_for_geom
from .units import (round_px, round_int, clamp01, scale_range_to_zoom_range,
                    num_or_str, is_expression, scale_to_zoom)
from .labeling import convert_labeling

# ラッパー系レンダラ（内部に本体レンダラを持つ）
_WRAPPER_RENDERERS = (
    "pointCluster", "pointDisplacement", "invertedPolygonRenderer",
    "mergedFeatureRenderer",
)

_WRAPPER_LABEL = {
    "pointCluster": "ポイントクラスタ",
    "pointDisplacement": "ポイント変位",
    "invertedPolygonRenderer": "逆ポリゴン",
    "mergedFeatureRenderer": "地物融合",
}


# ===================================================================== #
# スカラー属性の書き込み
# ===================================================================== #
def _fin_dash(props, final_width, opts, report, what):
    """SymbolProps の破線を、実際に出力する線幅に合わせて仕上げる。"""
    if opts is None:
        return list(props.dasharray or [])
    return finalize_dash(list(props.dasharray or []),
                         getattr(props, "dash_base_width", None),
                         final_width, opts, report, what)


def apply_symbol_props(style, props, geom, report, is_base=True, opts=None):
    """SymbolProps を geom に応じた .fgstyle キーへ書き込む。"""
    if props is None:
        return

    def _w(value, what, hairline=False):
        return (guard_width(value, opts, report, what, hairline)
                if opts else value)

    if geom == "Point":
        if props.color:
            style["circle-color"] = props.color
        if props.radius is not None:
            style["circle-radius"] = round_int(props.radius, minimum=2, maximum=30)
        if props.stroke_color:
            style["circle-stroke-color"] = props.stroke_color
        if props.stroke_width is not None:
            style["circle-stroke-width"] = _w(
                round_px(props.stroke_width, 2, minimum=0.0), "円の縁取り幅",
                props.stroke_hairline)
        if (is_base and props.opacity is not None
                and not is_expression(props.opacity) and props.opacity < 0.999):
            report.approx(
                "不透明度",
                "点シンボルの不透明度 {0:.2f} を反映できません（既定の 1.0 のまま）"
                .format(props.opacity),
                "点レイヤの不透明度は .fgstyle に対応キーがありません"
                "（定義書 付録B #8）。属性値色分けの opacity でのみ指定できます。")

    elif geom == "LineString":
        if props.color:
            style["line-color"] = props.color
        if props.width is not None:
            style["line-width"] = _w(
                round_px(props.width, 2, minimum=0.0), "線幅", props.hairline)
        if props.opacity is not None:
            style["line-opacity"] = clamp01(props.opacity)
        if props.dasharray is not None:
            # 破線は「線幅の倍数」なので、書き込んだ最終線幅を基準に直す
            style["line-dasharray"] = _fin_dash(
                props, style.get("line-width"), opts, report, "線")
        if props.casing_width:
            style["line-casing-width"] = _w(
                round_px(props.casing_width, 2, minimum=0.0), "縁取り幅")
            if props.casing_color:
                style["line-casing-color"] = props.casing_color

    elif geom == "Polygon":
        if props.color:
            style["fill-color"] = props.color
        if props.opacity is not None:
            style["fill-opacity"] = clamp01(props.opacity)
        if props.stroke_color:
            style["fill-outline-color"] = props.stroke_color
        if props.stroke_width is not None:
            style["line-width"] = _w(
                round_px(props.stroke_width, 2, minimum=0.0), "外周線幅",
                props.stroke_hairline)
        if props.stroke_opacity is not None:
            style["line-opacity"] = clamp01(props.stroke_opacity)
        if props.dasharray is not None:
            style["line-dasharray"] = _fin_dash(
                props, style.get("line-width"), opts, report, "外周線")


def _rule_color(props, geom, style):
    """ルール1件分の色を返す。"""
    if props.color:
        return props.color
    if geom == "Point":
        return style.get("circle-color", "#e63946")
    if geom == "LineString":
        return style.get("line-color", "#1d6fa4")
    return style.get("fill-color", "#2d8a4e")


def _rule_opacity(props, geom):
    """ルール1件分の不透明度（fgstyle の rule.opacity に載せる値）。"""
    if geom == "Polygon":
        return props.opacity
    if geom == "LineString":
        return props.opacity
    return props.opacity          # Point: circle-opacity / circle-stroke-opacity


def _rule_width(props, geom):
    """ルール1件分の幅（fgstyle の rule.width に載せる値）。"""
    if geom == "Point":
        return props.stroke_width       # 円の縁取り幅
    if geom == "LineString":
        return props.width              # 線幅
    return props.stroke_width           # 面：外周線幅


def _base_opacity_key(geom):
    return {"Polygon": "fill-opacity", "LineString": "line-opacity"}.get(geom)


def _base_width_key(geom):
    return {"Polygon": "line-width", "LineString": "line-width",
            "Point": "circle-stroke-width"}.get(geom)


def _attach_overrides(rule, props, geom, style, opts=None, report=None):
    """既定値と異なる opacity / width だけをルールに載せる。"""
    op = _rule_opacity(props, geom)
    wd = _rule_width(props, geom)

    base_op_key = _base_opacity_key(geom)
    base_op = style.get(base_op_key) if base_op_key else 1.0
    if base_op is None:
        base_op = 1.0
    base_wd_key = _base_width_key(geom)
    base_wd = style.get(base_wd_key) if base_wd_key else None

    if op is not None:
        if is_expression(op) or is_expression(base_op):
            rule["opacity"] = clamp01(op)
        elif abs(float(op) - float(base_op)) > 1e-6:
            rule["opacity"] = clamp01(op)
    hair = props.hairline if geom == "LineString" else props.stroke_hairline
    if wd is not None:
        if is_expression(wd) or is_expression(base_wd):
            rule["width"] = round_px(wd, 2, minimum=0.0)
        else:
            # 最小線幅・ヘアラインの補正を**先に**かけてから既定と比べる。
            # 補正後に既定と同じ値になるなら、ルールへ書く必要はない。
            width = guard_width(round_px(wd, 2, minimum=0.0), opts, report,
                                "区分ごとの線幅", hair) if opts is not None \
                else round_px(wd, 2, minimum=0.0)
            if base_wd is None or is_expression(base_wd) \
                    or abs(float(width) - float(base_wd)) > 1e-6:
                rule["width"] = width
    # 破線は色分けルールの opacity/width と違い、本体が filter 付きの
    # 別レイヤへ分割して表現する（MapLibre の line-dasharray はデータ駆動
    # 式を受け付けないため）。既定と異なるときだけ載せる。
    if geom in ("LineString", "Polygon") and props.dasharray is not None:
        # 倍数の基準になるのは「この区分で実際に描かれる線幅」。
        # ルールに width があればそれ、無ければレイヤ既定の line-width。
        eff_width = rule.get("width", style.get("line-width"))
        dash = list(props.dasharray)
        if opts is not None:
            dash = finalize_dash(dash, getattr(props, "dash_base_width", None),
                                 eff_width, opts, report, "区分ごとの線")
        base_dash = style.get("line-dasharray") or []
        if list(dash) != list(base_dash):
            rule["dasharray"] = dash

    # 縁取り（casing）。区分ごとに太さ・色が違うので必ず載せる。
    if geom == "LineString" and props.casing_width:
        width = round_px(props.casing_width, 2, minimum=0.0)
        if opts is not None:
            width = guard_width(width, opts, report, "区分ごとの縁取り幅")
        rule["casing_width"] = width
        if props.casing_color:
            rule["casing_color"] = props.casing_color
    return rule


# ===================================================================== #
# 線幅（細すぎ対策と単位の追跡）
# ===================================================================== #
def guard_width(value, opts, report, what, hairline=False):
    """細すぎて画面上で見えない線幅を、最小可視幅まで引き上げる。

    QGIS はサブピクセル幅の線をヘアライン（実質1デバイスピクセル）として
    描くのに対し、MapLibre は指定どおり細く描くため、QGIS では見えていた
    線がWEBでは消える。

    `hairline=True` は QGIS の**「非常に細い線」**（幅0だが描画される）。
    幅0でも引き上げる。線種が「線なし」(NoPen) の場合は呼び出し側で
    幅0・不透明度0にしてあるので、ここへは hairline=False で来る。
    """
    minimum = float(getattr(opts, "min_line_width", 0.0) or 0.0)
    if value is None or is_expression(value) or minimum <= 0:
        return value
    try:
        width = float(value)
    except (TypeError, ValueError):
        return value
    if width >= minimum:
        return value
    if width <= 0:
        if not hairline:
            return value        # 幅0＝線なし。意図的な指定なので触らない
        report.approx(
            "線幅",
            "{0} がQGISの「非常に細い線」（ヘアライン）のため {1:g}px にしました"
            .format(what, minimum),
            "QGISは幅0を1デバイスピクセルの細線として描きますが、MapLibre の "
            "line-width: 0 は文字どおり何も描きません。線を消したい場合は"
            "QGIS側で線種を「線なし」にしてください。")
        return minimum
    report.approx(
        "線幅",
        "{0} が {1:g}px と細く、WEB地図でほとんど見えないため {2:g}px へ"
        "引き上げました".format(what, width, minimum),
        "QGISはサブピクセル幅をヘアラインとして描きますが、MapLibre は"
        "指定どおり描きます。元の細さを保つなら「最小線幅」を0にしてください。")
    return minimum


# ===================================================================== #
# 破線（線幅変更への追従と、隙間が細すぎる対策）
# ===================================================================== #
def finalize_dash(pattern, base_width_px, final_width_px, opts, report, what):
    """破線パターンを最終線幅に合わせ直し、隙間が細すぎるものを広げる。

    MapLibre の `line-dasharray` は**線幅の倍数**で解釈されるため、
    次の2つの後処理が必要になる。

    1. 絶対長（mm/px）で書かれたカスタムダッシュは、倍数へ直したときの
       線幅（base_width_px）と、実際に出力する線幅（final_width_px）が
       違うと絶対長がずれる。「最小線幅」で 0.4px → 1.0px へ引き上げた
       場合、倍数のままだと破線も 2.5 倍に伸びてしまう。
    2. MapLibre は破線の切れ目もアンチエイリアスするため、隙間が 2px
       程度を下回ると左右のにじみが重なって実線に見える。線分の長さは
       変えず、隙間だけを下限まで広げる。
    """
    if not pattern or is_expression(final_width_px):
        return pattern
    try:
        final_w = float(final_width_px)
    except (TypeError, ValueError):
        return pattern
    if final_w <= 0:
        return pattern

    out = [float(v) for v in pattern]

    # --- 1. 線幅が変わっていたら絶対長を保つよう倍数を組み直す ------- #
    if base_width_px:
        try:
            base_w = float(base_width_px)
        except (TypeError, ValueError):
            base_w = 0.0
        if base_w > 0 and abs(base_w - final_w) > 1e-6:
            factor = base_w / final_w
            out = [v * factor for v in out]
            report.approx(
                "線種",
                "{0}の破線を線幅の変更（{1:g}px → {2:g}px）に合わせて"
                "組み直しました".format(what, base_w, final_w),
                "line-dasharray は線幅の倍数なので、倍数をそのままにすると"
                "破線の実寸が線幅と一緒に伸び縮みしてしまいます。"
                "QGISと同じ実寸（線分・隙間のpx）を保つよう再計算しています。")

    # --- 2. 隙間の下限 ---------------------------------------------- #
    minimum = float(getattr(opts, "min_dash_gap", 0.0) or 0.0)
    if minimum > 0:
        before = list(out)
        widened = []
        # 偶数番=線分、奇数番=隙間（MapLibre / Qt 共通）
        for index in range(1, len(out), 2):
            gap_px = out[index] * final_w
            if gap_px < minimum - 1e-9:
                widened.append((gap_px, minimum))
                out[index] = minimum / final_w
        if widened:
            report.approx(
                "線種",
                "{0}の破線の隙間が細く実線に見えるため {1:g}px へ広げました"
                "（{2} → {3}）".format(
                    what, minimum,
                    [round(v, 3) for v in before], [round(v, 3) for v in out]),
                "MapLibre は破線の切れ目もアンチエイリアスするため、"
                "隙間が {0:g}px を下回るとにじみが重なって実線に見えます"
                "（QGIS/Qt は切れ目を鋭く描くので同じ数値でも切れて見える）。"
                "線分の長さは変えていないので、区分ごとの『短い破線／"
                "長い破線』の差は保たれます。QGISの比率をそのまま出すなら"
                "「破線の最小隙間」を0にしてください。".format(minimum))

    return [round(v, 3) for v in out]


def report_unit_usage(report):
    """レイヤ内で使われた寸法単位と換算結果を1件にまとめて報告する。"""
    usage = getattr(report, "_unit_usage", None)
    if not usage:
        return
    setattr(report, "_unit_usage", {})
    parts = []
    for (unit, raw), px in sorted(usage.items())[:12]:
        parts.append("{0} {1:g} → {2:g}px".format(unit, raw, px))
    report.info(
        "単位",
        "QGIS側の寸法指定と換算結果: " + " / ".join(parts),
        "MapLibre はCSSピクセル基準です（`.fgstyle` の太さ・サイズも同じ）。"
        "mm/pt 指定は {0:g}dpi で換算しています。".format(report_dpi(report)))


def report_dpi(report):
    return getattr(report, "_dpi", 96.0)


# ===================================================================== #
# 属性値の型・表記ゆれ
# ===================================================================== #
_FULLWIDTH_RE = re.compile("[\uff01-\uff5e\u3000]")


def to_halfwidth(text):
    """全角英数記号・全角空白を半角へ。"""
    out = []
    for ch in str(text):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif code == 0x3000:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def looks_numeric(text):
    """文字列が数値として解釈できるか（半角に直したうえで判定）。"""
    try:
        float(to_halfwidth(str(text)).strip())
        return True
    except (TypeError, ValueError):
        return False


def value_variants(text):
    """判定値の「同じ意味になりうる別表記」を返す（元の値は含まない）。"""
    base = str(text)
    forms = {base}
    for candidate in (to_halfwidth(base), base.strip(),
                      to_halfwidth(base).strip()):
        forms.add(candidate)
    forms.discard(base)
    return sorted(f for f in forms if f != "")


def absorb_value_variations(rules, opts, report):
    """表記ゆれをプラグイン側で吸収する。

    1. 全角英数記号・全角空白・前後空白を含む判定値には、半角化／トリム
       した**別名ルール**を同じ色・同じ幅・同じ不透明度で追加する。
       MapLibre の match は完全一致なので、データ側がどちらの表記でも
       色が付くようになる。表記ゆれが無ければ何も追加しない。
    2. 重複した判定値は MapLibre が先勝ちで評価するため、後続の
       （どうせ効かない）ルールを取り除く。

    どちらも `.fgstyle` v1 の範囲内（ルールを増やす／減らすだけ）なので、
    UIの表を経由して「適用」しても壊れない。
    """
    out, seen, dropped, added = [], set(), [], []

    for rule in rules:
        if "num_min" in rule or "num_max" in rule:
            out.append(rule)
            continue

        text = str(rule.get("value", ""))
        if text in seen:
            dropped.append(text)
            continue
        seen.add(text)
        out.append(rule)

        if not opts.normalize_values:
            continue
        for variant in value_variants(text):
            if variant in seen:
                continue
            seen.add(variant)
            alias = dict(rule)
            alias["value"] = variant
            out.append(alias)
            added.append((text, variant))

    if dropped:
        report.info(
            "表記ゆれ",
            "重複していた判定値 {0} 件を取り除きました（MapLibreは先勝ち評価）"
            .format(len(dropped)),
            "該当: " + ", ".join(sorted(set(dropped))[:6]))
    if added:
        samples = ", ".join("{0!r}→{1!r}".format(a, b) for a, b in added[:4])
        report.info(
            "表記ゆれ",
            "半角化・トリムした別名ルール {0} 件を追加し、どちらの表記でも"
            "色が付くようにしました".format(len(added)),
            "QGIS側のデータ修正は不要です。凡例には別表記の行も並びます"
            "（不要なら「表記ゆれを吸収する」をOFFにしてください）。\n"
            "追加: " + samples)
    return out


def check_value_hygiene(rules, field, report):
    """判定値の表記ゆれを洗い出す。

    MapLibre の match は完全一致なので、全角・前後空白・重複は
    そのまま「一致しない」「先勝ちで隠れる」につながる。
    """
    fullwidth, padded, seen = [], [], set()
    for rule in rules:
        if "num_min" in rule or "num_max" in rule:
            continue
        value = rule.get("value")
        if value is None:
            continue
        text = str(value)
        if _FULLWIDTH_RE.search(text):
            fullwidth.append(text)
        if text != text.strip():
            padded.append(text)
        seen.add(text)

    absorbed = bool(getattr(report, "_variants_absorbed", False))

    if fullwidth:
        samples = ", ".join(
            "{0!r}→{1!r}".format(v, to_halfwidth(v)) for v in fullwidth[:4])
        if absorbed:
            report.info(
                "表記ゆれ",
                "判定値 {0} 件に全角文字がありましたが、半角の別名を追加して"
                "吸収しました".format(len(fullwidth)),
                "該当: " + samples)
        else:
            report.warn(
                "表記ゆれ",
                "判定値 {0} 件に全角文字が含まれています".format(len(fullwidth)),
                "MapLibre の match は完全一致です。データ側が半角なら一致しません。\n"
                "「表記ゆれを吸収する」を有効にすると別名ルールで自動対応します。\n"
                "該当: " + samples)
    if padded:
        if absorbed:
            report.info(
                "表記ゆれ",
                "判定値 {0} 件の前後に空白がありましたが、トリムした別名を"
                "追加して吸収しました".format(len(padded)),
                "該当: " + ", ".join(repr(v) for v in padded[:4]))
        else:
            report.warn(
                "表記ゆれ",
                "判定値 {0} 件の前後に空白があります".format(len(padded)),
                "該当: " + ", ".join(repr(v) for v in padded[:4]))



def _numeric_field_from_values(values):
    """カテゴリ値の型から、分類フィールドが数値型かを判定する。"""
    has_number = False
    for value in values:
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            has_number = True
        elif value not in (None, ""):
            return False
    return has_number


# ===================================================================== #
# 文字列ルール → フィールド型に応じた最終形
# ===================================================================== #
def _to_numeric_rules(rules, opts, report):
    """文字列ルールを step 式用の数値ルールへ変換する。

    判定値がすべて数値として読めなければ None（＝変換をあきらめる）。
    """
    converted = []
    for rule in rules:
        text = to_halfwidth(str(rule.get("value", ""))).strip()
        if not looks_numeric(text):
            return None
        value = float(text)
        new = dict(rule)
        new["value"] = ""
        new["num_min"] = num_or_str(value)
        new["num_max"] = num_or_str(value)
        converted.append(new)

    converted.sort(key=lambda r: float(r["num_min"]))

    if opts.close_numeric_gaps:
        converted = _insert_gap_rules(converted, report)
    return converted


def _insert_gap_rules(rules, report):
    """区分と区分のあいだへ不可視のダミー区分を挟む。

    step 式は「下限以上・次の下限未満」で色を決めるため、コード2の次が
    コード4だと 3 が 2 の色で塗られる。整数コードが飛んでいる箇所に
    不透明度0の区分を入れて、QGISと同じ「該当なしは描かない」に揃える。
    """
    out, inserted = [], 0
    for index, rule in enumerate(rules):
        out.append(rule)
        current = float(rule["num_min"])
        if index + 1 >= len(rules):
            # 最終区分の上限より大きい値も隠す（step式は上限を持たないため）
            if current == int(current):
                out.append({"value": "", "num_min": int(current) + 1,
                            "color": rule["color"], "opacity": 0.0,
                            "width": 0.0, "label": ""})
                inserted += 1
            continue
        following = float(rules[index + 1]["num_min"])
        if current != int(current) or following != int(following):
            continue
        if following - current <= 1:
            continue
        out.append({"value": "", "num_min": int(current) + 1,
                    "num_max": int(following) - 1,
                    "color": rule["color"], "opacity": 0.0, "width": 0.0,
                    "label": ""})
        inserted += 1
    if inserted:
        report.info(
            "色分け",
            "区分の隙間に不可視のダミー区分 {0} 件を挿入しました".format(inserted),
            "区分に無いコード値が直前の色で塗られるのを防ぎます。"
            "凡例には余分な行として出ます。")
    return out


def _emit_match_expression_style(style, geom, field, rules, report):
    """色・幅・不透明度のキーへ to-string 付きの match 式を直接出力する。"""
    color_key = _COLOR_KEY[geom]
    width_key = _WIDTH_KEY[geom]
    opacity_key = _OPACITY_KEY.get(geom)
    shape = _SHAPE[geom]

    default_color = style.get(color_key)
    if not isinstance(default_color, str):
        default_color = "#cccccc"

    style[color_key] = match_expression(
        field, [(r["value"], r["color"]) for r in rules], default_color)

    if any("width" in r for r in rules):
        base = style.get(width_key)
        style[width_key] = match_expression(
            field, [(r["value"], r.get("width", base)) for r in rules], base)
    if opacity_key and any("opacity" in r for r in rules):
        base = style.get(opacity_key)
        style[opacity_key] = match_expression(
            field, [(r["value"], r.get("opacity", base)) for r in rules], base)

    style["vt-legend"] = [
        {"label": r.get("label") or str(r["value"]),
         "color": r["color"], "shape": shape} for r in rules]
    style["vt-color-rule-enabled"] = False
    style["vt-color-rule-field"] = ""
    style["vt-color-rules"] = []

    report.need_patch("expr-safe")
    report.need_patch("legend")
    report.info(
        "色分け",
        "to-string 付きの match 式をキーへ直接出力しました",
        "属性が数値型でも文字列型でも一致します。凡例は vt-legend に"
        "書き出しました。")
    return True


def finalize_string_rules(style, geom, field, rules, numeric_field, opts, report):
    """組み立てた文字列ルールを、フィールドの型に応じた最終形にする。

    戻り値: (方式, style に入った実際のルールリスト)
      方式 … 'string' / 'numeric' / 'expression'
    """
    # 吸収するかどうかを先に知らせてから検査する（文言が変わる）
    setattr(report, "_variants_absorbed", bool(opts.normalize_values))
    check_value_hygiene(rules, field, report)
    # 表記ゆれの吸収（別名ルールの追加・重複の除去）は数値化の前に行う
    rules = absorb_value_variations(rules, opts, report)

    def _use_string(warn_type_mismatch):
        style["vt-color-rule-enabled"] = True
        style["vt-color-rule-field"] = field
        style["vt-color-rules"] = rules
        if warn_type_mismatch:
            _warn_numeric_match(report, field,
                                [r.get("value") for r in rules[:3]])
        return "string", rules

    if not numeric_field:
        return _use_string(False)

    numeric_rules = _to_numeric_rules(rules, opts, report)
    if numeric_rules is None:
        report.warn(
            "色分け",
            "数値として読めない判定値が混じっているため文字列ルールにしました")
        return _use_string(True)

    style["vt-color-rule-enabled"] = True
    style["vt-color-rule-field"] = field
    style["vt-color-rules"] = numeric_rules
    report.info(
        "色分け",
        "分類フィールド『{0}』が数値型のため、数値ルール（step式）として"
        "出力しました".format(field),
        "MapLibre の match は型に厳密で、文字列ルールだと数値属性に"
        "一致しません。step 式なら型に関係なく正しく描画されます。"
        "区分に無い値は直前の区分の色になります。")
    return "numeric", numeric_rules


# ===================================================================== #
# ===================================================================== #
# MapLibre式の組み立て
# ===================================================================== #
def _get_as_string(field):
    """数値属性でも文字列ルールと一致するように to-string で包む。"""
    return ["to-string", ["coalesce", ["get", field], ""]]


def match_expression(field, pairs, default):
    """[(判定値, 出力), …] → MapLibre の match 式。"""
    expr = ["match", _get_as_string(field)]
    for value, out in pairs:
        expr.append(str(value))
        expr.append(out)
    expr.append(default)
    return expr


def step_expression(field, pairs, default):
    """[(下限, 出力), …]（下限昇順） → MapLibre の step 式。"""
    expr = ["step", ["get", field], default]
    for lower, out in sorted(pairs, key=lambda x: float(x[0])):
        expr.append(float(lower))
        expr.append(out)
    return expr


def _values_differ(values):
    """出力を出し分ける必要があるか（式が混じる場合は常に True）。"""
    seen = []
    for v in values:
        if v is None:
            continue
        if is_expression(v):
            return True
        if v not in seen:
            seen.append(v)
    return len(seen) > 1


#: 幾何種別ごとの「色分けルールでは表現できないが、キーには入れられる」項目
#  値: (styleキー, SymbolProps の属性名)
_EXTRA_KEYS = {
    "Point": [("circle-radius", "radius"),
              ("circle-stroke-color", "stroke_color")],
    "Polygon": [("fill-outline-color", "stroke_color")],
    "LineString": [],
}


def _entries_for(entries, mode):
    """`_apply_per_rule_extras` 用に、方式に応じたキーへ揃える。"""
    if mode != "numeric":
        return entries
    out = []
    for key, props in entries:
        try:
            out.append((float(to_halfwidth(str(key)).strip()), props))
        except (TypeError, ValueError):
            return []
    return out


def _apply_per_rule_extras(style, geom, field, entries, numeric, opts, report):
    """カテゴリ／区分ごとに出し分けたいが `vt-color-rules` では表現できない
    項目を、キーへ直接 MapLibre 式として書き込む。

    entries: [(判定値 or 下限, SymbolProps), …]
    """
    if not opts.allow_expressions or not field or not entries:
        return

    for key, attr in _EXTRA_KEYS.get(geom, []):
        values = [getattr(props, attr) for _k, props in entries]
        if not _values_differ(values):
            continue
        default = style.get(key)
        pairs = [(k, v if v is not None else default)
                 for k, v in zip([e[0] for e in entries], values)]
        if numeric:
            style[key] = step_expression(field, pairs, default)
        else:
            style[key] = match_expression(field, pairs, default)
        report.info(
            "高度な表現",
            "『{0}』を区分ごとに出し分ける式を出力しました".format(key),
            "`vt-color-rules` では表現できない項目のため、キーに MapLibre 式を"
            "直接入れています。")
        report.need_patch("expr-safe")


# ===================================================================== #
# メイン
# ===================================================================== #
def convert_vector_layer(layer, geom, opts, report):
    """QgsVectorLayer（スタイル読込済み）→ .fgstyle の style 辞書。"""
    style = default_style(geom)
    setattr(report, "_dpi", opts.dpi)

    renderer = None
    try:
        renderer = layer.renderer()
    except Exception:
        renderer = None

    if renderer is None:
        report.error("レンダラ", "レンダラを取得できませんでした。既定値を出力します。")
    else:
        renderer = _unwrap(renderer, report)
        _dispatch(renderer, style, geom, opts, report)

    # レイヤ全体の不透明度（QGISではシンボル不透明度に掛け合わされる）
    _apply_layer_opacity(layer, style, geom, report)

    # 縮尺依存表示
    if opts.convert_scale_visibility:
        _apply_scale_visibility(layer, style, opts, report)

    # ラベル
    if opts.convert_labeling:
        convert_labeling(layer, style, opts, report)

    report_unit_usage(report)
    return style


def _unwrap(renderer, report):
    """ラッパー系レンダラを内側のレンダラへ置き換える。"""
    seen = 0
    while renderer is not None and seen < 5:
        try:
            rtype = renderer.type()
        except Exception:
            break
        if rtype not in _WRAPPER_RENDERERS:
            break
        label = _WRAPPER_LABEL.get(rtype, rtype)
        try:
            inner = renderer.embeddedRenderer()
        except Exception:
            inner = None
        if inner is None:
            report.warn("レンダラ",
                        "{0}レンダラの内部レンダラを取得できませんでした".format(label))
            break
        report.warn(
            "レンダラ",
            "{0}レンダラは再現できないため、内部のシンボル定義のみ変換しました"
            .format(label),
            "クラスタ化・変位配置・面の反転はMapLibre側では行われません。")
        renderer = inner.clone() if hasattr(inner, "clone") else inner
        seen += 1
    return renderer


def _dispatch(renderer, style, geom, opts, report):
    try:
        rtype = renderer.type()
    except Exception:
        rtype = ""

    if rtype == "singleSymbol":
        _convert_single(renderer, style, geom, opts, report)
    elif rtype == "categorizedSymbol":
        _convert_categorized(renderer, style, geom, opts, report)
    elif rtype == "graduatedSymbol":
        _convert_graduated(renderer, style, geom, opts, report)
    elif rtype == "RuleRenderer":
        _convert_rulebased(renderer, style, geom, opts, report)
    elif rtype == "nullSymbol":
        _convert_null(style, geom, report)
    elif rtype == "heatmapRenderer":
        report.warn("レンダラ",
                    "ヒートマップレンダラは変換できません。既定の単色になります。")
    elif rtype == "25dRenderer":
        report.warn("レンダラ",
                    "2.5Dレンダラは変換できません。既定の単色になります。")
    elif rtype == "embeddedSymbol":
        report.warn("レンダラ",
                    "地物埋め込みシンボルは変換できません。既定の単色になります。")
    else:
        report.warn("レンダラ",
                    "未対応のレンダラ種別『{0}』のため既定値を出力しました".format(rtype))


# --------------------------------------------------------------------- #
def _convert_single(renderer, style, geom, opts, report):
    try:
        symbol = renderer.symbol()
    except Exception:
        symbol = None
    props = props_for_geom(symbol, geom, opts, report, "シンボル")
    apply_symbol_props(style, props, geom, report, opts=opts)
    style["vt-color-rule-enabled"] = False
    style["vt-color-rule-field"] = ""
    style["vt-color-rules"] = []
    report.info("レンダラ", "単一シンボルとして変換しました")


def _convert_null(style, geom, report):
    if geom == "Polygon":
        style["fill-opacity"] = 0.0
        style["line-width"] = 0.0
    elif geom == "LineString":
        style["line-opacity"] = 0.0
        style["line-width"] = 0.0
    else:
        report.warn("レンダラ",
                    "非表示（nullSymbol）レンダラですが、点レイヤは不透明度を"
                    "指定できないため半径を最小にしました")
        style["circle-radius"] = 2
        style["circle-stroke-width"] = 0.0
    report.info("レンダラ", "非表示レンダラとして変換しました")


# --------------------------------------------------------------------- #
def _resolve_class_field(renderer, report):
    """分類／段階レンダラの分類フィールドを取り出して検証する。"""
    try:
        raw = renderer.classAttribute()
    except Exception:
        raw = ""
    field = plain_field_name(raw)
    if field is None:
        report.warn(
            "分類フィールド",
            "分類が式『{0}』に基づいているため色分けを変換できません".format(raw),
            "MapLibreの [\"get\", field] はフィールド名のみ受け付けます。"
            "式の結果を属性列として持たせてから再実行してください。")
        return None
    return field


def _base_symbol(renderer, fallback_symbols):
    try:
        s = renderer.sourceSymbol()
        if s is not None:
            return s
    except Exception:
        pass
    for s in fallback_symbols:
        if s is not None:
            return s
    return None


def _is_null_value(value):
    if value is None:
        return True
    try:
        from qgis.PyQt.QtCore import QVariant
        if isinstance(value, QVariant):
            return value.isNull()
    except Exception:
        pass
    try:
        # PyQGIS の NULL は QVariant() 相当。文字列化すると 'NULL'
        if repr(value) == "NULL":
            return True
    except Exception:
        pass
    return False


def _value_to_text(value):
    if _is_null_value(value):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


# --------------------------------------------------------------------- #
def _convert_categorized(renderer, style, geom, opts, report):
    field = _resolve_class_field(renderer, report)

    try:
        categories = list(renderer.categories())
    except Exception:
        categories = []

    if not categories:
        report.warn("分類", "カテゴリが1件もありません")
        return

    # 「すべての他の値」＝ 末尾の NULL値カテゴリ
    fallback_index = None
    if opts.categorized_fallback_as_default:
        for i in range(len(categories) - 1, -1, -1):
            if _is_null_value(categories[i].value()):
                fallback_index = i
                break

    symbols = [c.symbol() for c in categories]
    base = _base_symbol(renderer, symbols)
    base_props = props_for_geom(base, geom, opts, report, "基本シンボル")
    apply_symbol_props(style, base_props, geom, report, opts=opts)

    if fallback_index is not None:
        fb_props = props_for_geom(categories[fallback_index].symbol(), geom,
                                  opts, report, "『すべての他の値』のシンボル")
        apply_symbol_props(style, fb_props, geom, report, is_base=False, opts=opts)
        report.info("分類",
                    "『すべての他の値』カテゴリを既定色に割り当てました")

    if field is None:
        return

    rules = []
    entries = []
    skipped = 0
    for i, cat in enumerate(categories):
        if i == fallback_index:
            continue
        try:
            if not cat.renderState():
                skipped += 1
                continue
        except Exception:
            pass

        raw = cat.value()
        text = _value_to_text(raw)

        props = props_for_geom(cat.symbol(), geom, opts, report,
                               "カテゴリ『{0}』".format(text))
        entries.append((text, props))
        rule = {"value": text, "color": _rule_color(props, geom, style)}
        _attach_overrides(rule, props, geom, style, opts, report)
        try:
            _attach_label(rule, cat.label(), text, opts)
        except Exception:
            pass
        rules.append(rule)

    if skipped:
        report.info("分類",
                    "チェックの外れたカテゴリ {0} 件を除外しました".format(skipped))

    rules = _truncate_rules(rules, opts, report)
    if not rules:
        report.warn("分類", "変換できるカテゴリがありませんでした")
        return

    numeric_field = _numeric_field_from_values(
        [c.value() for i, c in enumerate(categories) if i != fallback_index])
    mode, final_rules = finalize_string_rules(
        style, geom, field, rules, numeric_field, opts, report)

    _note_label_patch(final_rules, report)
    _apply_per_rule_extras(style, geom, field,
                           _entries_for(entries, mode), mode == "numeric",
                           opts, report)

    apply_default_color(style, geom, opts, report,
                        "分類", "どのカテゴリにも該当しない地物",
                        has_explicit_fallback=fallback_index is not None)

    report.info("レンダラ",
                "分類シンボル（{0}件）を変換しました".format(len(final_rules)))
    report.info("色分け",
                "MapLibreのmatch式は完全一致のみです。属性値の表記ゆれ"
                "（全角/半角・前後空白）があると一致しません。")


# --------------------------------------------------------------------- #
def _convert_graduated(renderer, style, geom, opts, report):
    field = _resolve_class_field(renderer, report)

    try:
        ranges = list(renderer.ranges())
    except Exception:
        ranges = []

    if not ranges:
        report.warn("段階", "分類区分が1件もありません")
        return

    base = _base_symbol(renderer, [r.symbol() for r in ranges])
    base_props = props_for_geom(base, geom, opts, report, "基本シンボル")
    apply_symbol_props(style, base_props, geom, report, opts=opts)

    if field is None:
        return

    active = []
    skipped = 0
    for rg in ranges:
        try:
            if not rg.renderState():
                skipped += 1
                continue
        except Exception:
            pass
        active.append(rg)

    if skipped:
        report.info("段階", "チェックの外れた区分 {0} 件を除外しました".format(skipped))

    active.sort(key=lambda r: float(r.lowerValue()))

    # 区間の隙間チェック（定義書 付録B #1）
    for i in range(len(active) - 1):
        upper = float(active[i].upperValue())
        nxt = float(active[i + 1].lowerValue())
        if nxt - upper > 1e-9:
            report.warn(
                "段階",
                "区分 {0:g}–{1:g} と {2:g}– の間に隙間があります".format(
                    float(active[i].lowerValue()), upper, nxt),
                "MapLibreのstep式は区間上限を持たないため、"
                "隙間の値は手前の区分の色で塗られます（定義書 付録B #1）。")

    rules = []
    entries = []
    for rg in active:
        props = props_for_geom(rg.symbol(), geom, opts, report,
                               "区分 {0:g}–{1:g}".format(
                                   float(rg.lowerValue()), float(rg.upperValue())))
        entries.append((float(rg.lowerValue()), props))
        rule = {
            "value": "",
            "num_min": num_or_str(float(rg.lowerValue())),
            "num_max": num_or_str(float(rg.upperValue())),
            "color": _rule_color(props, geom, style),
        }
        _attach_overrides(rule, props, geom, style, opts, report)
        try:
            auto = "{0:g}～{1:g}".format(float(rg.lowerValue()),
                                        float(rg.upperValue()))
            _attach_label(rule, rg.label(), auto, opts)
        except Exception:
            pass
        rules.append(rule)

    rules = _truncate_rules(rules, opts, report)
    if not rules:
        report.warn("段階", "変換できる区分がありませんでした")
        return

    style["vt-color-rule-enabled"] = True
    style["vt-color-rule-field"] = field
    style["vt-color-rules"] = rules

    _note_label_patch(rules, report)
    _apply_per_rule_extras(style, geom, field, entries, True, opts, report)
    _handle_out_of_range(style, rules, geom, opts, report, active)

    report.info("レンダラ",
                "段階シンボル（{0}区分）を数値ルールへ変換しました".format(len(rules)))
    report.info(
        "色分け",
        "num_max は凡例表示専用で、実際の区間上限は次の区分の num_min で決まります"
        "（定義書 付録B #1）。")


_COLOR_KEY_FOR = {"Point": "circle-color", "LineString": "line-color",
                  "Polygon": "fill-color"}


def apply_default_color(style, geom, opts, report, category, what,
                        has_explicit_fallback=False):
    """どのルールにも該当しない地物の色を決める。

    QGISは分類・段階・ルールベースのいずれでも「該当なし」を描画しないが、
    MapLibre の match / step / case 式は**必ず既定値へフォールバック**する。
    以前は既定の不透明度を0にして消していたが、
      * 区分ごとに不透明度・線幅を全ルールへ書き戻す必要があり、
        数百区分のスタイルでファイルが膨らむ
      * 型不一致などで1件も一致しないとレイヤ全体が消え、原因が分からない
    ため、**該当なしは既定色で描く**方針に統一した。

    QGIS側に「すべての他の値」カテゴリ／ELSEルールがあれば、その色が
    そのまま既定色になっているのでここでは触らない。
    """
    if has_explicit_fallback:
        return
    key = _COLOR_KEY_FOR.get(geom)
    if not key:
        return
    color = getattr(opts, "default_color", "") or ""
    if not color:
        return
    style[key] = color
    report.info(
        category,
        "{0}は既定色 {1} で描画されます".format(what, color),
        "QGISでは描画されませんが、MapLibre の式は必ず既定値へ"
        "フォールバックします。色は変換設定の「該当なしの既定色」で"
        "変更できます。")


def _handle_out_of_range(style, rules, geom, opts, report, ranges):
    """最小区分の下限を下回る地物の扱い。"""
    lowest = float(ranges[0].lowerValue()) if ranges else 0.0
    highest = float(ranges[-1].upperValue()) if ranges else 0.0

    apply_default_color(style, geom, opts, report,
                        "段階", "{0:g} 未満の地物".format(lowest))
    report.info(
        "段階",
        "{0:g} を超える値は最後の区分の色になります".format(highest),
        "step式は最終区分の上限を表現できません（定義書 付録B #1）。")


# --------------------------------------------------------------------- #
# ルールベース: 式による出力（`vt-color-rules` で表現できない場合）
# --------------------------------------------------------------------- #
_COLOR_KEY = {"Point": "circle-color", "LineString": "line-color",
              "Polygon": "fill-color"}
_WIDTH_KEY = {"Point": "circle-stroke-width", "LineString": "line-width",
              "Polygon": "line-width"}
_OPACITY_KEY = {"LineString": "line-opacity", "Polygon": "fill-opacity"}
_SHAPE = {"Point": "circle", "LineString": "line", "Polygon": "fill"}


def _rule_scale_condition(rule, cond, opts, report):
    """ルール固有の縮尺範囲を、ズーム条件として式に畳み込む。"""
    try:
        min_scale = float(rule.minimumScale() or 0)
        max_scale = float(rule.maximumScale() or 0)
    except Exception:
        return cond
    if min_scale <= 0 and max_scale <= 0:
        return cond

    bounds = []
    z_lo = scale_to_zoom(min_scale, opts)
    z_hi = scale_to_zoom(max_scale, opts)
    if z_lo is not None:
        bounds.append([">=", ["zoom"], round(max(0.0, z_lo), 2)])
    if z_hi is not None:
        bounds.append(["<", ["zoom"], round(min(24.0, z_hi), 2)])
    if not bounds:
        return cond
    report.info(
        "ルールベース",
        "ルール固有の縮尺範囲をズーム条件として式に組み込みました")
    return ["all", cond] + bounds


def _legend_color(props, fallback):
    """凡例に出せる（文字列の）色を返す。"""
    color = props.color if props is not None else None
    if isinstance(color, str) and color:
        return color
    return fallback


def _convert_rulebased_expr(children, style, geom, opts, report):
    """ルールを MapLibre の case 式へ変換する。成功したら True。"""
    items = []
    else_props = None
    else_label = ""

    for rule in children:
        try:
            if hasattr(rule, "active") and not rule.active():
                continue
            symbol = rule.symbol()
            label = rule.label() or ""
            expr_text = rule.filterExpression()
        except Exception:
            return False

        props = props_for_geom(symbol, geom, opts, report,
                               "ルール『{0}』".format(label or expr_text))
        try:
            is_else = rule.isElse()
        except Exception:
            is_else = not (expr_text or "").strip()
        if is_else:
            else_props, else_label = props, label
            continue

        cond, err = mlexpr.try_translate(expr_text)
        if cond is None:
            report.warn(
                "ルールベース",
                "式『{0}』を MapLibre 式へ変換できませんでした".format(expr_text),
                err or "")
            return False
        cond = _rule_scale_condition(rule, mlexpr.as_boolean(cond), opts, report)
        items.append((cond, props, label))

    if not items:
        return False

    # スカラーの既定値は ELSE ルール（無ければ先頭ルール）から取る
    base_props = else_props or items[0][1]
    apply_symbol_props(style, base_props, geom, report, opts=opts)

    color_key = _COLOR_KEY[geom]
    width_key = _WIDTH_KEY[geom]
    opacity_key = _OPACITY_KEY.get(geom)
    shape = _SHAPE[geom]

    # 該当なしは既定色で描く（消さない）
    if else_props is None:
        apply_default_color(style, geom, opts, report,
                            "ルールベース", "どの条件にも該当しない地物")
    default_color = style.get(color_key)
    default_width = style.get(width_key)
    default_opacity = style.get(opacity_key) if opacity_key else None

    # --- 色 ---------------------------------------------------------- #
    color_expr = ["case"]
    for cond, props, _label in items:
        color_expr.append(cond)
        color_expr.append(_rule_color(props, geom, style))
    color_expr.append(default_color)
    style[color_key] = color_expr

    # --- 幅 ---------------------------------------------------------- #
    widths = [_rule_width(props, geom) for _c, props, _l in items]
    if _values_differ(widths + [default_width]):
        expr = ["case"]
        for (cond, _p, _l), width in zip(items, widths):
            expr.append(cond)
            expr.append(width if width is not None else default_width)
        expr.append(default_width)
        style[width_key] = expr

    # --- 不透明度 ---------------------------------------------------- #
    if opacity_key:
        opacities = [_rule_opacity(props, geom) for _c, props, _l in items]
        if _values_differ(opacities + [default_opacity]):
            expr = ["case"]
            for (cond, _p, _l), value in zip(items, opacities):
                expr.append(cond)
                expr.append(value if value is not None else 1.0)
            expr.append(default_opacity)
            style[opacity_key] = expr

    # --- 凡例 -------------------------------------------------------- #
    legend = []
    for _cond, props, label in items:
        legend.append({"label": label,
                       "color": _legend_color(props, default_color
                                              if isinstance(default_color, str)
                                              else "#cccccc"),
                       "shape": shape})
    if else_props is not None:
        legend.append({"label": else_label or "その他",
                       "color": _legend_color(else_props, "#cccccc"),
                       "shape": shape})
    elif isinstance(default_color, str):
        # 該当なしは既定色で描かれるので凡例にも出す
        legend.append({"label": "その他", "color": default_color,
                       "shape": shape})
    style["vt-legend"] = legend

    # 色分けルールは使わない（case式が直接キーに入っているため）
    style["vt-color-rule-enabled"] = False
    style["vt-color-rule-field"] = ""
    style["vt-color-rules"] = []

    report.need_patch("expr-safe")
    report.need_patch("legend")
    report.info(
        "レンダラ",
        "ルールベース（{0}件）を MapLibre の case 式として出力しました"
        .format(len(items)),
        "単一フィールドの色分けルールでは表現できない条件のため、"
        "色・幅・不透明度のキーに式を直接入れています。"
        "凡例は vt-legend キーに書き出しました。")
    return True


def _simple_path_covers(children):
    """従来の `vt-color-rules` だけで表現できるルール構成か。"""
    fields, kinds, count = set(), set(), 0
    for rule in children:
        try:
            if hasattr(rule, "active") and not rule.active():
                continue
            if rule.isElse():
                continue
            expr_text = rule.filterExpression()
        except Exception:
            return False
        cond = parse_condition(expr_text)
        if cond is None:
            return False
        if cond.field:
            fields.add(cond.field)
        kinds.add(cond.kind)
        count += 1
        try:
            if (rule.minimumScale() or 0) > 0 or (rule.maximumScale() or 0) > 0:
                return False
        except Exception:
            pass
    return count > 0 and len(fields) <= 1 and len(kinds) <= 1


def _convert_rulebased(renderer, style, geom, opts, report):
    try:
        root = renderer.rootRule()
        children = list(root.children())
    except Exception:
        children = []

    if not children:
        report.warn("ルールベース", "ルールが1件もありません")
        return

    # 単一フィールドの色分けルールで足りない構成は、式として出力する
    if not _simple_path_covers(children) and opts.allow_expressions:
        if _convert_rulebased_expr(children, style, geom, opts, report):
            return
        report.info("ルールベース",
                    "式として出力できなかったため、変換できるルールのみを"
                    "色分けルールとして出力します")

    # 入れ子ルールは非対応
    for r in children:
        try:
            if r.children():
                report.warn(
                    "ルールベース",
                    "入れ子のルール『{0}』は展開できないため無視しました".format(
                        r.label() or r.filterExpression()))
        except Exception:
            pass

    parsed = []
    else_symbol = None
    for r in children:
        try:
            expr = r.filterExpression()
            sym = r.symbol()
            active = r.active() if hasattr(r, "active") else True
        except Exception:
            continue
        if not active:
            continue
        try:
            if r.isElse():
                else_symbol = sym
                continue
        except Exception:
            pass

        cond = parse_condition(expr)
        if cond is None:
            report.warn(
                "ルールベース",
                "式『{0}』は変換できないため無視しました".format(expr),
                "変換できるのは「\"列\" = '値'」「\"列\" IN (...)」"
                "「\"列\" IS NULL」「\"列\" >= a AND \"列\" < b」の形だけです。")
            continue
        if cond.kind == "else":
            else_symbol = sym
            continue
        parsed.append((cond, sym, r))

    # 基本シンボル
    base_sym = else_symbol or (parsed[0][1] if parsed else None)
    base_props = props_for_geom(base_sym, geom, opts, report, "基本シンボル")
    apply_symbol_props(style, base_props, geom, report, opts=opts)

    if not parsed:
        report.warn("ルールベース", "変換できるルールがありませんでした")
        return

    # フィールドの一致確認
    fields = [c.field for c, _s, _r in parsed if c.field]
    field = fields[0] if fields else None
    if field and len(set(fields)) > 1:
        report.warn(
            "ルールベース",
            "複数のフィールド {0} が使われているため、『{1}』のルールのみ変換しました"
            .format(sorted(set(fields)), field))
        parsed = [(c, s, r) for c, s, r in parsed if c.field == field]

    kinds = set(c.kind for c, _s, _r in parsed)
    if len(kinds) > 1:
        report.warn(
            "ルールベース",
            "文字列条件と数値範囲条件が混在しているため、数値範囲のみ変換しました",
            "`.fgstyle` の色分けは配列全体で1モードです（定義書 付録B #4）。")
        parsed = [(c, s, r) for c, s, r in parsed if c.kind == "range"]

    as_step = False   # 数値化は finalize_string_rules 側で一括して行う

    rules = []
    for cond, sym, r_obj in parsed:
        props = props_for_geom(sym, geom, opts, report, "ルール")
        color = _rule_color(props, geom, style)
        try:
            rule_label = r_obj.label()
        except Exception:
            rule_label = ""

        if cond.kind == "value":
            for v in cond.values:
                if as_step:
                    rule = {"value": "", "num_min": num_or_str(float(v)),
                            "num_max": num_or_str(float(v)), "color": color}
                else:
                    rule = {"value": str(v), "color": color}
                _attach_overrides(rule, props, geom, style, opts, report)
                _attach_label(rule, rule_label, v, opts)
                rules.append(rule)
        else:
            rule = {"value": "", "color": color}
            if cond.num_min is not None:
                rule["num_min"] = num_or_str(cond.num_min)
            if cond.num_max is not None:
                rule["num_max"] = num_or_str(cond.num_max)
            if cond.num_min is None:
                report.warn(
                    "ルールベース",
                    "下限のない範囲条件（{0} 以下）は描画に反映されません".format(
                        cond.num_max),
                    "step式は下限のみで区間を決めます（定義書 付録B #2）。")
            _attach_overrides(rule, props, geom, style, opts, report)
            auto = "{0:g}～{1:g}".format(cond.num_min or 0, cond.num_max or 0)
            _attach_label(rule, rule_label, auto, opts)
            rules.append(rule)

    if "range" in kinds or as_step:
        rules.sort(key=lambda r: float(r.get("num_min", float("-inf"))))


    rules = _truncate_rules(rules, opts, report)
    if not rules:
        return

    numeric_field = ("range" in kinds) or all(
        c.numeric_literal for c, _s, _r in parsed)
    if "range" in kinds:
        # すでに num_min/num_max を持つので変換不要
        style["vt-color-rule-enabled"] = True
        style["vt-color-rule-field"] = field or ""
        style["vt-color-rules"] = rules
        mode, final_rules = "numeric", rules
        check_value_hygiene(rules, field or "", report)
    else:
        mode, final_rules = finalize_string_rules(
            style, geom, field or "", rules, numeric_field, opts, report)

    _note_label_patch(final_rules, report)
    apply_default_color(style, geom, opts, report,
                        "ルールベース", "どのルールにも該当しない地物",
                        has_explicit_fallback=else_symbol is not None)

    report.info("レンダラ",
                "ルールベース（{0}件）を変換しました".format(len(final_rules)))


# --------------------------------------------------------------------- #
def _attach_label(rule, label, value_text, opts):
    """凡例表示名をルールへ付ける（判定値と別名のときだけ）。"""
    if not opts.emit_rule_labels:
        return rule
    if not label:
        return rule
    if str(label).strip() == str(value_text).strip():
        return rule
    rule["label"] = str(label)
    return rule


def _note_label_patch(rules, report):
    """凡例名を出力したことを知らせる。"""
    if any("label" in r for r in rules):
        report.info(
            "凡例",
            "QGISの凡例名を rule.label（凡例表示名）として出力しました",
            "WEB地図のレイヤパネルに、判定値ではなくQGISの凡例名が出ます。")


def _warn_numeric_match(report, field, samples):
    """数値リテラルの判定値を文字列ルールとして出力したことを知らせる。"""
    setattr(report, "_numeric_match_field", field or "")
    report.info(
        "色分け",
        "判定値が数値（例: {0}）ですが、文字列ルールとして出力しました".format(
            ", ".join(str(s) for s in samples[:3])),
        "本体側の判定入力は to-string / to-number で型を揃えるため、"
        "データ側の『{0}』が数値型でも文字列型でも一致します。".format(field))


def _truncate_rules(rules, opts, report):
    if len(rules) > opts.max_rules:
        report.warn(
            "色分け",
            "ルールが {0} 件あるため先頭 {1} 件のみ出力しました".format(
                len(rules), opts.max_rules))
        return rules[:opts.max_rules]
    return rules


def _apply_layer_opacity(layer, style, geom, report):
    """レイヤ不透明度をシンボル側の不透明度へ畳み込む。"""
    try:
        opacity = float(layer.opacity())
    except Exception:
        return
    if opacity >= 0.999:
        return

    if geom == "Point":
        report.approx(
            "不透明度",
            "レイヤ不透明度 {0:.2f} を反映できません".format(opacity),
            "点レイヤの不透明度に対応キーがありません（定義書 付録B #8）。")
        return

    def _mul(value):
        if value is None:
            return None
        if is_expression(value):
            return ["*", value, opacity]
        return clamp01(float(value) * opacity)

    keys = ("fill-opacity", "line-opacity") if geom == "Polygon" else ("line-opacity",)
    for key in keys:
        if key in style and style[key] is not None:
            style[key] = _mul(style[key])

    for rule in style.get("vt-color-rules", []):
        if "opacity" in rule and rule["opacity"] is not None:
            rule["opacity"] = _mul(rule["opacity"])

    report.info("不透明度",
                "レイヤ不透明度 {0:.2f} をシンボルの不透明度に畳み込みました"
                .format(opacity))


def _apply_scale_visibility(layer, style, opts, report):
    try:
        if not layer.hasScaleBasedVisibility():
            return
        min_scale = layer.minimumScale()
        max_scale = layer.maximumScale()
    except Exception:
        return

    minzoom, maxzoom = scale_range_to_zoom_range(min_scale, max_scale, opts)
    style["minzoom"] = minzoom
    style["maxzoom"] = maxzoom
    report.info(
        "縮尺依存表示",
        "1:{0:g}〜1:{1:g} を minzoom={2:g} / maxzoom={3:g} に換算しました".format(
            min_scale or 0, max_scale or 0, minzoom, maxzoom),
        "基準緯度 {0:g}°・{1:g}dpi での換算です。".format(
            opts.reference_latitude, opts.dpi))
