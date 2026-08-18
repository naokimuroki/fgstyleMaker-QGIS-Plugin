# -*- coding: utf-8 -*-
"""ラスタレイヤ → .fgstyle。

ラスタは実データを開かないと QgsRasterLayer を構築できないため、
プロジェクトXMLの `<pipe><rasterrenderer opacity="...">` を直接読む。
（読むのは不透明度と縮尺依存表示だけで、レンダラの解釈は行わない）
"""

import urllib.parse

from .defaults import default_style
from .units import scale_range_to_zoom_range, clamp01


def detect_raster_kind(source, provider=""):
    """ForestGeo Studio 本体 `_layer_kind()` と同じ判定で種別を返す。"""
    src = urllib.parse.unquote(source or "")
    src_lower = src.lower()
    prov = (provider or "").lower()
    if "pbf" in src_lower or "mvt" in src_lower or "vector" in src_lower:
        return "VectorTile"
    if "{z}" in src or "url=" in src or prov in ("wms", "xyz"):
        return "Raster(Tile)"
    return "Raster"


def convert_raster_element(element, source, provider, opts, report):
    """`<maplayer>` のQDomElement（またはNone）からラスタスタイルを作る。"""
    kind = detect_raster_kind(source, provider)
    style = default_style(kind)

    opacity = _read_opacity(element)
    if opacity is not None:
        style["raster-opacity"] = clamp01(opacity)
    else:
        report.info("不透明度", "不透明度を読み取れなかったため 1.0 にしました")

    if opts.convert_scale_visibility:
        min_scale, max_scale, enabled = _read_scale_visibility(element)
        if enabled:
            minzoom, maxzoom = scale_range_to_zoom_range(min_scale, max_scale, opts)
            style["minzoom"] = minzoom
            style["maxzoom"] = maxzoom
            report.info(
                "縮尺依存表示",
                "1:{0:g}〜1:{1:g} を minzoom={2:g} / maxzoom={3:g} に換算しました"
                .format(min_scale or 0, max_scale or 0, minzoom, maxzoom))

    _warn_renderer_kind(element, report)
    return style


# --------------------------------------------------------------------- #
def _child(element, tag):
    """QDomElement / ElementTree どちらでも子要素を返す。"""
    if element is None:
        return None
    # QDomElement
    if hasattr(element, "firstChildElement"):
        e = element.firstChildElement(tag)
        return None if e.isNull() else e
    # xml.etree
    return element.find(tag)


def _attr(element, name, default=None):
    if element is None:
        return default
    if hasattr(element, "attribute"):
        if hasattr(element, "hasAttribute") and not element.hasAttribute(name):
            return default
        return element.attribute(name)
    return element.get(name, default)


def _read_opacity(element):
    pipe = _child(element, "pipe")
    holder = pipe if pipe is not None else element
    rr = _child(holder, "rasterrenderer")
    if rr is None and pipe is not None:
        rr = _child(element, "rasterrenderer")
    val = _attr(rr, "opacity")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _read_scale_visibility(element):
    flag = _attr(element, "hasScaleBasedVisibilityFlag", "0")
    enabled = str(flag) in ("1", "true", "True")
    try:
        min_scale = float(_attr(element, "minScale", 0) or 0)
    except (TypeError, ValueError):
        min_scale = 0.0
    try:
        max_scale = float(_attr(element, "maxScale", 0) or 0)
    except (TypeError, ValueError):
        max_scale = 0.0
    return min_scale, max_scale, enabled


_RENDERER_LABEL = {
    "singlebandgray": "単バンドグレー",
    "singlebandpseudocolor": "単バンド疑似カラー",
    "paletted": "パレット",
    "hillshade": "陰影図",
    "contour": "等高線",
}


def _warn_renderer_kind(element, report):
    pipe = _child(element, "pipe")
    rr = _child(pipe if pipe is not None else element, "rasterrenderer")
    if rr is None:
        return
    rtype = _attr(rr, "type", "") or ""
    if rtype in ("multibandcolor", ""):
        return
    label = _RENDERER_LABEL.get(rtype, rtype)
    report.warn(
        "ラスタレンダラ",
        "『{0}』の配色はWEB出力側では再現されません".format(label),
        "MapLibre は元画像／タイルをそのまま描画します。"
        "QGIS上の配色を反映するには、着色済みのラスタまたはタイルを"
        "書き出してから出力してください。")

    for tag, msg in (("brightnesscontrast", "明るさ・コントラスト調整"),
                     ("huesaturation", "色相・彩度調整"),
                     ("rasterresampler", "リサンプリング設定")):
        node = _child(pipe if pipe is not None else element, tag)
        if node is not None:
            report.info("ラスタ", "{0}は変換対象外です".format(msg))
