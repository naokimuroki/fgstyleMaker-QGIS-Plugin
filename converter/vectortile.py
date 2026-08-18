# -*- coding: utf-8 -*-
"""ベクトルタイルレイヤ（QgsVectorTileLayer）→ .fgstyle の vt-* キー。"""

import re
import urllib.parse

from .defaults import default_style
from .expressions import parse_condition, plain_field_name
from .symbols import props_for_geom
from .vector import (absorb_value_variations, check_value_hygiene,
                     guard_width, finalize_dash)
from .units import (color_to_hex, round_int, round_px, clamp01,
                    to_pixels, scale_range_to_zoom_range, num_or_str)

_GEOM_NAME = {0: "Point", 1: "LineString", 2: "Polygon"}


def extract_tile_url(source):
    """レイヤソース文字列からタイルURLテンプレートを取り出す。

    ForestGeo Studio 本体 `_extract_tile_url()` と同じ規則。
    """
    src = urllib.parse.unquote(source or "")
    m = re.search(r"url=([^&]+)", src)
    if m:
        return m.group(1)
    if "{z}" in src and "{x}" in src and "{y}" in src:
        return src
    m = re.search(r"(https?://[^|&\s]+)", src)
    if m:
        return m.group(1)
    return ""


def _geom_name(geometry_type):
    try:
        return _GEOM_NAME.get(int(geometry_type), "Polygon")
    except Exception:
        return "Polygon"


def convert_vector_tile_layer(layer, opts, report, layer_id=""):
    """QgsVectorTileLayer → style 辞書。"""
    style = default_style("VectorTile")

    try:
        style["tile_url"] = extract_tile_url(layer.source())
    except Exception:
        pass
    style["vt-source"] = layer_id or ""

    renderer = None
    try:
        renderer = layer.renderer()
    except Exception:
        renderer = None

    if renderer is None:
        report.error("レンダラ", "ベクトルタイルのレンダラを取得できませんでした")
        return style

    try:
        styles = list(renderer.styles())
    except Exception:
        styles = []

    active = []
    for st in styles:
        try:
            if st.isEnabled():
                active.append(st)
        except Exception:
            active.append(st)

    if not active:
        report.warn("レンダラ", "有効なスタイルがありません")
        return style

    # --- 描画対象の (source-layer, 幾何種別) を1組だけ選ぶ ----------- #
    groups = {}
    for st in active:
        try:
            key = (st.layerName(), _geom_name(st.geometryType()))
        except Exception:
            continue
        groups.setdefault(key, []).append(st)

    if not groups:
        report.warn("レンダラ", "スタイルからソースレイヤを判別できませんでした")
        return style

    # 最もスタイル数の多い組を採用（迷ったら定義順で先頭）
    chosen_key = max(groups.keys(), key=lambda k: (len(groups[k]),
                                                   -list(groups).index(k)))
    chosen = groups[chosen_key]
    source_layer, geom = chosen_key

    if len(groups) > 1:
        others = ["{0}／{1}".format(k[0], k[1]) for k in groups if k != chosen_key]
        report.warn(
            "レンダラ",
            "『{0}／{1}』のみ変換しました。他の {2} 組は出力していません".format(
                source_layer, geom, len(others)),
            "`.fgstyle` は1レイヤにつきソースレイヤ1つ・幾何種別1つだけです"
            "（定義書 9.1）。残りは: " + " / ".join(others[:8]))

    style["vt-source-layer"] = source_layer or ""
    style["vt-geom-type"] = geom
    if not source_layer:
        report.error(
            "レンダラ",
            "source-layer が空です。この状態ではHTML出力が失敗します",
            "ForestGeo Studio 側で ValueError になります（定義書 付録B #10）。")

    # --- フィルタ無しスタイル＝既定、フィルタ付き＝色分けルール ------ #
    default_style_obj = None
    filtered = []
    for st in chosen:
        try:
            expr = (st.filterExpression() or "").strip()
        except Exception:
            expr = ""
        if expr == "":
            if default_style_obj is None:
                default_style_obj = st
        else:
            filtered.append((expr, st))

    if default_style_obj is not None:
        base_props = props_for_geom(_symbol_of(default_style_obj), geom, opts,
                                    report, "ベクトルタイルの基本シンボル")
        _apply_vt_props(style, base_props, geom, opts, report)
    else:
        # フィルタ無しのスタイルが1つも無い＝QGIS上は「該当なしは描かない」。
        # MapLibre は必ず既定値へフォールバックするので、既定色で描く。
        # 幅・不透明度だけは先頭スタイルから拾って見た目を合わせる。
        base_props = props_for_geom(_symbol_of(chosen[0]), geom, opts, report,
                                    "ベクトルタイルの基本シンボル")
        _apply_vt_props(style, base_props, geom, opts, report)
        _apply_vt_default_color(style, geom, opts, report)

    _convert_vt_zoom(chosen, style, report)

    if filtered:
        _convert_vt_rules(filtered, style, geom, opts, report)

    _convert_vt_labeling(layer, style, opts, report, source_layer, geom)
    return style


def _symbol_of(st):
    try:
        return st.symbol()
    except Exception:
        return None


# --------------------------------------------------------------------- #
def _apply_vt_default_color(style, geom, opts, report):
    """どのフィルタにも該当しない地物の色を既定色にする。"""
    key = {"Polygon": "fill-color", "LineString": "vt-line-color"}.get(
        geom, "vt-circle-color")
    color = getattr(opts, "default_color", "") or ""
    if not color:
        return
    style[key] = color
    if geom == "Polygon":
        # 外周線も既定色に合わせる。フィルタ付きスタイルの1枚目の色を
        # 使ってしまうと、全ポリゴンがその色で縁取られてしまう。
        style["vt-outline-color"] = color
    report.info(
        "色分け",
        "どのスタイルにも該当しない地物は既定色 {0} で描画されます".format(color),
        "QGISのベクトルタイルスタイルはフィルタに合わない地物を描きませんが、"
        "MapLibre の match / step 式は必ず既定値へフォールバックします。")


def _apply_vt_props(style, props, geom, opts, report):
    if props is None:
        return
    if geom == "Polygon":
        if props.color:
            style["fill-color"] = props.color
        if props.opacity is not None:
            style["fill-opacity"] = clamp01(props.opacity)
        if props.stroke_color:
            style["vt-outline-color"] = props.stroke_color
        if props.stroke_width is not None:
            style["vt-outline-width"] = guard_width(
                round_px(props.stroke_width, 2, minimum=0.0, maximum=10.0),
                opts, report, "外周線幅", props.stroke_hairline)
    elif geom == "LineString":
        if props.color:
            style["vt-line-color"] = props.color
        if props.width is not None:
            style["vt-line-width"] = guard_width(
                round_px(props.width, 2, minimum=0.0),
                opts, report, "線幅", props.hairline)
        if props.opacity is not None:
            style["vt-line-opacity"] = clamp01(props.opacity)
    else:  # Point
        if props.color:
            style["vt-circle-color"] = props.color
        if props.radius is not None:
            style["vt-circle-radius"] = round_int(props.radius, minimum=2, maximum=30)
        if props.stroke_color:
            style["vt-circle-stroke"] = props.stroke_color
        if props.opacity is not None and props.opacity < 0.999:
            report.approx(
                "不透明度",
                "点の不透明度 {0:.2f} を反映できません".format(props.opacity),
                "ベクトルタイルの点は不透明度が 1.0 固定です（定義書 9.4）。")


def _vt_rule_color(props, style, geom):
    if props.color:
        return props.color
    return {"Polygon": style.get("fill-color", "#2d8a4e"),
            "LineString": style.get("vt-line-color", "#1d6fa4")}.get(
                geom, style.get("vt-circle-color", "#e63946"))


def _line_width_px(st, geom, opts):
    """スタイルの線幅(px)。比較用なので概算で十分。"""
    if geom != "LineString":
        return 0.0
    props = props_for_geom(_symbol_of(st), geom, opts, _NULL_REPORT,
                           "幅の比較")
    try:
        return float(props.width or 0.0)
    except (TypeError, ValueError):
        return 0.0


class _NullReport(object):
    """幅の比較のためだけに変換するときの捨てレポート。"""

    def info(self, *a, **k):
        pass

    warn = approx = error = info

    def need_patch(self, *a, **k):
        pass


_NULL_REPORT = _NullReport()


def merge_casing_styles(filtered, geom, opts, report):
    """同じ条件のスタイルが複数あれば「縁取り＋中心線」としてまとめる。

    道路記号の定番構成:

        edges_1_casing  N13_003 IS 1  幅4.5px  濃い色   ← 下に敷く縁取り
        edges_1_inner   N13_003 IS 1  幅3.0px  淡い色   ← 上に描く中心線

    QGISは定義順に描く（後が上）ので、**最後のスタイルが中心線**、
    それより前で最も太いものが縁取りになる。
    以前は「判定値の重複」として後ろを捨てていたため、
    縁取りだけが残って中心線の色が失われていた。

    戻り値: [(式, 中心線スタイル, 縁取りスタイル or None), ...]
    """
    groups = []
    index_of = {}
    for expr, st in filtered:
        key = (expr or "").strip()
        if key in index_of:
            groups[index_of[key]][1].append(st)
        else:
            index_of[key] = len(groups)
            groups.append((expr, [st]))

    out = []
    merged = 0
    for expr, styles in groups:
        if len(styles) == 1:
            out.append((expr, styles[0], None))
            continue
        main = styles[-1]
        main_w = _line_width_px(main, geom, opts)
        below = styles[:-1]
        widest = max(below, key=lambda st: _line_width_px(st, geom, opts))
        if geom == "LineString" and \
                _line_width_px(widest, geom, opts) > main_w:
            out.append((expr, main, widest))
            merged += 1
        else:
            # 縁取り構成ではない（上のほうが太い／線以外）。最後だけ使う。
            out.append((expr, main, None))
            report.approx(
                "スタイル",
                "同じ条件のスタイルが {0} 枚重なっているため、"
                "いちばん上の1枚だけ変換しました".format(len(styles)),
                "条件: {0}".format(expr))
    if merged:
        report.info(
            "スタイル",
            "同じ条件の重ね描き {0} 組を「縁取り＋中心線」として変換しました"
            .format(merged),
            "太いほうを縁取り（casing）として本線の下に敷きます。"
            "以前は重複扱いで中心線が捨てられていました。")
    return out


def _style_label(st, fallback=""):
    """スタイル名（QGISの凡例に出る名前）。"""
    for name in ("styleName", "name"):
        try:
            value = getattr(st, name)()
        except Exception:
            continue
        if value:
            return str(value)
    return fallback


_VT_WIDTH_BASE = {"Polygon": "vt-outline-width", "LineString": "vt-line-width",
                  "Point": None}
_VT_OPACITY_BASE = {"Polygon": "fill-opacity", "LineString": "vt-line-opacity",
                    "Point": None}


def _vt_rule_extras(rule, props, style, geom, opts, report):
    """区分ごとの幅・不透明度・線種を、既定と違うときだけ載せる。"""
    width = props.width if geom == "LineString" else props.stroke_width
    opacity = props.opacity
    hair = props.hairline if geom == "LineString" else props.stroke_hairline

    wkey = _VT_WIDTH_BASE.get(geom)
    base_w = style.get(wkey) if wkey else None
    if width is not None:
        # 補正を先にかけてから既定と比べる（同じ値なら書かない）
        width = guard_width(round_px(width, 2, minimum=0.0), opts, report,
                            "区分ごとの線幅", hair)
        if base_w is None or _differs(width, base_w):
            rule["width"] = width

    okey = _VT_OPACITY_BASE.get(geom)
    base_o = style.get(okey) if okey else None
    if opacity is not None and (base_o is None or _differs(opacity, base_o)):
        rule["opacity"] = clamp01(opacity)

    if geom == "Polygon" and props.stroke_color:
        # QGISは「塗りと同じ色で縁取る」定義が多い。1色に丸めると
        # 全ポリゴンが同じ縁取り色になるので、区分ごとに載せる。
        if props.stroke_color != style.get("vt-outline-color"):
            rule["outline_color"] = props.stroke_color

    if geom in ("LineString", "Polygon") and props.dasharray is not None:
        eff_width = rule.get("width", style.get(wkey) if wkey else None)
        dash = finalize_dash(list(props.dasharray),
                             getattr(props, "dash_base_width", None),
                             eff_width, opts, report, "区分ごとの線")
        base_key = ("vt-line-dasharray" if geom == "LineString"
                    else "vt-outline-dasharray")
        if list(dash) != list(style.get(base_key) or []):
            rule["dasharray"] = dash
    return rule


def _casing_of(casing_style, geom, opts, report):
    """縁取りスタイル → {"casing_color":…, "casing_width":…}。無ければ {}。"""
    if casing_style is None or geom != "LineString":
        return {}
    props = props_for_geom(_symbol_of(casing_style), geom, opts, report,
                           "縁取り（casing）")
    if props is None or not props.width:
        return {}
    width = guard_width(round_px(props.width, 2, minimum=0.0), opts, report,
                        "縁取り幅", props.hairline)
    out = {"casing_width": width}
    if props.color:
        out["casing_color"] = props.color
    return out


def _differs(a, b):
    try:
        return abs(float(a) - float(b)) > 1e-6
    except (TypeError, ValueError):
        return a != b


def _convert_vt_rules(filtered, style, geom, opts, report):
    """フィルタ式付きのスタイル群 → vt-color-rules。"""
    parsed = []
    for expr, st, casing_st in merge_casing_styles(filtered, geom, opts, report):
        cond = parse_condition(expr)
        if cond is None or cond.kind == "else":
            report.warn(
                "色分け",
                "フィルタ式『{0}』は変換できないため無視しました".format(expr),
                "単一フィールドに対する = / IS / IN / 範囲比較だけが"
                "色分けルールになります。")
            continue
        parsed.append((cond, st, casing_st))

    if not parsed:
        return

    fields = [c.field for c, _s, _cs in parsed if c.field]
    if not fields:
        return
    field = fields[0]
    if len(set(fields)) > 1:
        report.warn(
            "色分け",
            "複数フィールド {0} が使われているため『{1}』のみ変換しました".format(
                sorted(set(fields)), field))
        parsed = [t for t in parsed if t[0].field == field]

    kinds = set(t[0].kind for t in parsed)
    if len(kinds) > 1:
        report.warn("色分け",
                    "文字列条件と数値条件が混在しているため数値条件のみ変換しました")
        parsed = [t for t in parsed if t[0].kind == "range"]
        kinds = {"range"}

    rules = []
    numeric_literal = False
    for cond, st, casing_st in parsed:
        props = props_for_geom(_symbol_of(st), geom, opts, report,
                               "フィルタ付きスタイル")
        color = _vt_rule_color(props, style, geom)
        label = _style_label(st)
        casing = _casing_of(casing_st, geom, opts, report)
        if cond.kind == "value":
            numeric_literal = numeric_literal or cond.numeric_literal
            for value in cond.values:
                rule = {"value": str(value), "color": color}
                if opts.emit_rule_labels and label and label != str(value):
                    rule["label"] = label
                rule.update(casing)
                rules.append(_vt_rule_extras(rule, props, style, geom,
                                             opts, report))
        else:
            rule = {"value": "", "color": color}
            if cond.num_min is not None:
                rule["num_min"] = num_or_str(cond.num_min)
            if cond.num_max is not None:
                rule["num_max"] = num_or_str(cond.num_max)
            if opts.emit_rule_labels and label:
                rule["label"] = label
            rule.update(casing)
            rules.append(_vt_rule_extras(rule, props, style, geom,
                                         opts, report))

    if "range" in kinds:
        rules.sort(key=lambda r: float(r.get("num_min", float("-inf"))))
    else:
        # 表記ゆれ（全角/半角・前後空白）の検査と吸収は fgb と同じ扱い
        setattr(report, "_variants_absorbed", bool(opts.normalize_values))
        check_value_hygiene(rules, field, report)
        rules = absorb_value_variations(rules, opts, report)

    if len(rules) > opts.max_rules:
        report.warn("色分け", "ルールが多いため先頭 {0} 件のみ出力しました".format(
            opts.max_rules))
        rules = rules[:opts.max_rules]

    style["vt-color-rule-enabled"] = True
    style["vt-color-rule-field"] = field
    style["vt-color-rules"] = rules
    report.info("色分け",
                "フィルタ式付きスタイル {0} 件を色分けルールへ変換しました".format(
                    len(rules)))
    if any("label" in r for r in rules):
        report.info(
            "凡例",
            "QGISのスタイル名を rule.label（凡例表示名）として出力しました")
    if numeric_literal:
        report.info(
            "色分け",
            "判定値が数値ですが文字列ルールとして出力しました",
            "本体側の判定入力は to-string / to-number で型を揃えるため、"
            "ベクトルタイル側の属性が数値でも文字列でも一致します。")


def _convert_vt_zoom(styles, style, report):
    """スタイルのズーム範囲。.fgstyle のVTはラベル以外にズームキーを持たない。"""
    zooms = []
    for st in styles:
        try:
            zmin, zmax = st.minZoomLevel(), st.maxZoomLevel()
        except Exception:
            continue
        if zmin is not None and zmin >= 0:
            zooms.append(("min", zmin))
        if zmax is not None and zmax >= 0:
            zooms.append(("max", zmax))
    if zooms:
        report.warn(
            "ズーム範囲",
            "スタイルにズームレベル制限が設定されていますが変換できません",
            "`.fgstyle` のベクトルタイルは minzoom/maxzoom を持ちません"
            "（ラベルのみ vt-label-minzoom/maxzoom で指定可能・定義書 4章）。")


# --------------------------------------------------------------------- #
def _convert_vt_labeling(layer, style, opts, report, source_layer, geom):
    try:
        labeling = layer.labeling()
    except Exception:
        labeling = None
    if labeling is None:
        return

    try:
        lstyles = [s for s in labeling.styles() if s.isEnabled()]
    except Exception:
        lstyles = []

    if not lstyles:
        return

    # 描画対象と同じソースレイヤのものを優先
    pick = None
    for s in lstyles:
        try:
            if s.layerName() == source_layer:
                pick = s
                break
        except Exception:
            pass
    if pick is None:
        pick = lstyles[0]

    try:
        settings = pick.labelSettings()
    except Exception:
        settings = None
    if settings is None:
        return

    field_name = getattr(settings, "fieldName", "") or ""
    if bool(getattr(settings, "isExpression", False)):
        plain = plain_field_name(field_name)
        if not plain:
            report.warn("ラベル",
                        "ベクトルタイルのラベルが式のため変換できません: {0}".format(
                            field_name))
            return
        field_name = plain
    if not field_name:
        return

    style["vt-label-enabled"] = True
    style["vt-label-field"] = field_name

    try:
        fmt = settings.format()
    except Exception:
        fmt = None
    if fmt is not None:
        size_px = to_pixels(fmt.size(), fmt.sizeUnit(), opts, report,
                            "ラベル文字サイズ")
        if size_px is not None:
            style["vt-label-size"] = round_int(size_px, minimum=6, maximum=48)
        c = color_to_hex(fmt.color())
        if c:
            style["vt-label-color"] = c
        try:
            buf = fmt.buffer()
            if buf is not None and buf.enabled():
                style["vt-label-halo"] = True
                bc = color_to_hex(buf.color())
                if bc:
                    style["vt-label-halo-color"] = bc
                report.info(
                    "ラベル",
                    "ベクトルタイルの縁取り幅は 1.5px 固定です（定義書 9.5）")
            else:
                style["vt-label-halo"] = False
        except Exception:
            pass

    if opts.convert_scale_visibility:
        try:
            if bool(getattr(settings, "scaleVisibility", False)):
                zmin, zmax = scale_range_to_zoom_range(
                    getattr(settings, "minimumScale", 0),
                    getattr(settings, "maximumScale", 0), opts)
                style["vt-label-minzoom"] = zmin
                style["vt-label-maxzoom"] = zmax
        except Exception:
            pass
