# -*- coding: utf-8 -*-
"""ForestGeo Studio 側 `_default_style()` と同一の既定値。

`.fgstyle` 定義書 v1 に準拠する。ここを ForestGeo Studio 本体の
`dialog.py::_default_style()` と食い違わせないこと。
"""

STYLE_FILE_FORMAT = "forestgeostudio-layer-style"
STYLE_FILE_VERSION = 1

# 部分ラベル系（点・線・面で共通）
_LABEL_DEFAULTS = {
    "label-enabled": False,
    "label-field": "",
    "text-size": 12,
    "text-color": "#222222",
    "text-halo-enabled": True,
    "text-halo-color": "#ffffff",
    "text-halo-width": 1.5,
    "text-minzoom": 0,
    "text-maxzoom": 24,
}

_RULE_DEFAULTS = {
    "vt-color-rule-enabled": False,
    "vt-color-rule-field": "",
    "vt-color-rules": [],
}


def default_style(geom):
    """geom に応じた既定スタイル辞書を返す。"""
    if geom == "Point":
        style = {
            "geom": "Point",
            "circle-color": "#e63946",
            "circle-radius": 8,
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": 1.5,
            "minzoom": 0,
            "maxzoom": 24,
        }
        style.update(_LABEL_DEFAULTS)
        style.update(_RULE_DEFAULTS)
        return style

    if geom == "LineString":
        style = {
            "geom": "LineString",
            "line-color": "#1d6fa4",
            "line-width": 2.0,
            "line-opacity": 1.0,
            # 破線パターン（線幅の倍数）。空リストは実線
            "line-dasharray": [],
            "minzoom": 0,
            "maxzoom": 24,
        }
        style.update(_LABEL_DEFAULTS)
        style.update(_RULE_DEFAULTS)
        return style

    if geom == "Polygon":
        style = {
            "geom": "Polygon",
            "fill-color": "#2d8a4e",
            "fill-opacity": 0.5,
            "fill-outline-color": "#ffffff",
            "line-opacity": 1.0,
            # 本体UIには無いが、外周線幅として有効なキー（定義書 7章）
            "line-width": 1.0,
            # 外周線の破線パターン（線幅の倍数）
            "line-dasharray": [],
            "minzoom": 0,
            "maxzoom": 24,
        }
        style.update(_LABEL_DEFAULTS)
        style.update(_RULE_DEFAULTS)
        return style

    if geom == "VectorTile":
        style = {
            "geom": "VectorTile",
            "tile_url": "",
            "vt-source": "",
            "vt-source-layer": "",
            "vt-geom-type": "Polygon",
            # Polygon
            "fill-color": "#2d8a4e",
            "fill-opacity": 0.6,
            "vt-outline-color": "#ffffff",
            "vt-outline-width": 1.0,
            "vt-outline-dasharray": [],
            # LineString
            "vt-line-color": "#1d6fa4",
            "vt-line-width": 2.0,
            "vt-line-opacity": 1.0,
            "vt-line-dasharray": [],
            # Point
            "vt-circle-color": "#e63946",
            "vt-circle-radius": 6,
            "vt-circle-stroke": "#ffffff",
            "vt-tree-svg-enabled": False,
            # Label
            "vt-label-enabled": False,
            "vt-label-field": "",
            "vt-label-size": 12,
            "vt-label-color": "#222222",
            "vt-label-halo": True,
            "vt-label-halo-color": "#ffffff",
            "vt-label-minzoom": 0,
            "vt-label-maxzoom": 24,
        }
        style.update(_RULE_DEFAULTS)
        return style

    if geom in ("Raster", "Raster(Tile)"):
        return {
            "geom": geom,
            "raster-opacity": 1.0,
            "minzoom": 0,
            "maxzoom": 24,
        }

    return {"geom": geom}


# --------------------------------------------------------------------- #
# 「色分けルールの opacity / width が効くキー」の対応表（定義書 11.5）
# --------------------------------------------------------------------- #
#   geom / vt-geom-type -> (既定の width を持つキー, 既定の opacity を持つキー)
WIDTH_BASE_KEY = {
    "Point": "circle-stroke-width",
    "LineString": "line-width",
    "Polygon": "line-width",             # 面では外周線の幅
    "VectorTile:Point": None,            # 実装側で 1.5 固定
    "VectorTile:LineString": "vt-line-width",
    "VectorTile:Polygon": "vt-outline-width",
}

OPACITY_BASE_KEY = {
    "Point": None,                       # 実装側で 1.0 固定
    "LineString": "line-opacity",
    "Polygon": "fill-opacity",
    "VectorTile:Point": None,            # 実装側で 1.0 固定
    "VectorTile:LineString": "vt-line-opacity",
    "VectorTile:Polygon": "fill-opacity",
}
