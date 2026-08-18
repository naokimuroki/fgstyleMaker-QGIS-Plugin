# -*- coding: utf-8 -*-
"""QGISのラベル設定 → .fgstyle の label-* / text-* キー。"""

from .expressions import plain_field_name
from .units import (color_to_hex, to_pixels, round_int, round_px,
                    scale_range_to_zoom_range)


def _first_labeling_settings(labeling, report):
    """QgsAbstractVectorLayerLabeling から QgsPalLayerSettings を取り出す。"""
    if labeling is None:
        return None
    try:
        ltype = labeling.type()
    except Exception:
        ltype = ""

    if ltype == "rule-based":
        try:
            root = labeling.rootRule()
            children = list(root.children())
        except Exception:
            children = []
        active = []
        for r in children:
            try:
                if r.active() and r.settings() is not None:
                    active.append(r)
            except Exception:
                pass
        if not active:
            report.warn("ラベル", "ルールベースラベルに有効なルールがありません")
            return None
        if len(active) > 1:
            report.warn(
                "ラベル",
                "ルールベースラベルの {0} 件中、先頭のルールのみ変換しました"
                .format(len(active)),
                "`.fgstyle` のラベル設定はレイヤに1組だけです。")
        return active[0].settings()

    try:
        return labeling.settings()
    except Exception:
        return None


def convert_labeling(layer, style, opts, report):
    """ラベル設定を style へ書き込む。"""
    try:
        enabled = bool(layer.labelsEnabled())
    except Exception:
        enabled = False

    if not enabled:
        style["label-enabled"] = False
        return

    try:
        labeling = layer.labeling()
    except Exception:
        labeling = None

    settings = _first_labeling_settings(labeling, report)
    if settings is None:
        style["label-enabled"] = False
        report.warn("ラベル", "ラベル設定を取得できませんでした")
        return

    # --- 対象フィールド -------------------------------------------- #
    field_name = getattr(settings, "fieldName", "") or ""
    is_expression = bool(getattr(settings, "isExpression", False))

    if is_expression:
        plain = plain_field_name(field_name)
        if plain:
            field_name = plain
        else:
            report.warn(
                "ラベル",
                "ラベルが式『{0}』のため変換できません".format(field_name),
                "`.fgstyle` の label-field は属性名のみです"
                "（MapLibre側は [\"to-string\", [\"get\", 名前]] を生成）。")
            style["label-enabled"] = False
            return

    if not field_name:
        style["label-enabled"] = False
        report.warn("ラベル", "ラベル対象のフィールドが空のため無効化しました")
        return

    style["label-enabled"] = True
    style["label-field"] = field_name

    # --- 文字書式 ---------------------------------------------------- #
    try:
        fmt = settings.format()
    except Exception:
        fmt = None

    if fmt is not None:
        size_px = to_pixels(fmt.size(), fmt.sizeUnit(), opts, report, "ラベル文字サイズ")
        if size_px is not None:
            style["text-size"] = round_int(size_px, minimum=6, maximum=48)
        hexcolor = color_to_hex(fmt.color())
        if hexcolor:
            style["text-color"] = hexcolor

        try:
            if float(fmt.opacity()) < 0.999:
                report.warn(
                    "ラベル",
                    "文字の不透明度 {0:.2f} は変換できません".format(fmt.opacity()),
                    "`.fgstyle` に text-opacity 相当のキーがありません。")
        except Exception:
            pass

        _convert_buffer(fmt, style, opts, report)
        _warn_unsupported_text_features(fmt, settings, report)
    else:
        report.warn("ラベル", "文字書式を取得できませんでした")

    # --- 縮尺依存 ---------------------------------------------------- #
    if opts.convert_scale_visibility:
        try:
            if bool(getattr(settings, "scaleVisibility", False)):
                minzoom, maxzoom = scale_range_to_zoom_range(
                    getattr(settings, "minimumScale", 0),
                    getattr(settings, "maximumScale", 0), opts)
                style["text-minzoom"] = minzoom
                style["text-maxzoom"] = maxzoom
                report.info(
                    "ラベル",
                    "ラベルの縮尺依存表示を text-minzoom={0:g} / text-maxzoom={1:g} "
                    "に換算しました".format(minzoom, maxzoom))
        except Exception:
            pass


def _convert_buffer(fmt, style, opts, report):
    """バッファ（縁取り）→ text-halo-*。"""
    try:
        buf = fmt.buffer()
    except Exception:
        buf = None

    if buf is None:
        return

    try:
        enabled = bool(buf.enabled())
    except Exception:
        enabled = False

    if not enabled:
        style["text-halo-enabled"] = False
        # ★ ForestGeo Studio 側は text-halo-enabled を見ずに
        #    text-halo-color / width をそのまま paint へ渡す（定義書 付録B #5）。
        #    縁取りを本当に消すには幅を0にする必要がある。
        style["text-halo-width"] = 0.0
        report.info(
            "ラベル",
            "縁取り無効のため text-halo-width=0 も併せて出力しました",
            "text-halo-enabled=false だけでは縁取りが消えないためです"
            "（定義書 付録B #5）。")
        return

    style["text-halo-enabled"] = True
    hexcolor = color_to_hex(buf.color())
    if hexcolor:
        style["text-halo-color"] = hexcolor
    w = to_pixels(buf.size(), buf.sizeUnit(), opts, report, "ラベル縁取り幅")
    if w is not None:
        style["text-halo-width"] = round_px(w, 2, minimum=0.0, maximum=8.0)

    try:
        if float(buf.opacity()) < 0.999:
            report.approx("ラベル",
                          "縁取りの不透明度 {0:.2f} は変換できません".format(
                              buf.opacity()))
    except Exception:
        pass


def _warn_unsupported_text_features(fmt, settings, report):
    """MapLibre側に対応キーが無いラベル装飾を洗い出す。"""
    checks = [
        ("background", "背景（枠）", "テキスト背景は変換できません"),
        ("shadow", "影", "ドロップシャドウは変換できません"),
        ("mask", "マスク", "マスクは変換できません"),
    ]
    for attr, label, msg in checks:
        try:
            obj = getattr(fmt, attr)()
            if obj is not None and obj.enabled():
                report.warn("ラベル", msg)
        except Exception:
            pass

    try:
        if fmt.font().bold() or fmt.font().italic():
            report.approx(
                "ラベル",
                "太字／斜体は変換できません（Open Sans Regular 固定）",
                "`.fgstyle` は text-font を固定で出力します（定義書 8章）。")
    except Exception:
        pass

    try:
        placement = int(getattr(settings, "placement", -1))
        # 0 = AroundPoint 相当。厳密な対応は取らず、既定以外なら注意喚起にとどめる。
        if placement not in (-1, 0):
            report.info(
                "ラベル",
                "ラベル配置方式は変換対象外です（MapLibre既定の配置になります）")
    except Exception:
        pass
