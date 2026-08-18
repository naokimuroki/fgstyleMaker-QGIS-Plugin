# -*- coding: utf-8 -*-
"""変換の取りまとめと .fgstyle の書き出し。"""

import json
import os
import re
import traceback

from .defaults import STYLE_FILE_FORMAT, STYLE_FILE_VERSION, default_style
from .features import detect_unsupported
from .options import ConvertOptions
from .report import ConversionReport
from .raster import convert_raster_element
from .vector import convert_vector_layer
from .vectortile import convert_vector_tile_layer

_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ConvertedLayer(object):
    """1レイヤ分の変換結果。"""

    __slots__ = ("source", "style", "report", "payload", "ok")

    def __init__(self, source, style, report, ok=True):
        self.source = source
        self.style = style
        self.report = report
        self.ok = ok
        self.payload = build_payload(source.name, style) if style else None

    @property
    def name(self):
        return self.source.name

    @property
    def kind(self):
        return self.source.kind

    def to_json(self, indent=2):
        return json.dumps(self.payload, ensure_ascii=False, indent=indent)


# ===================================================================== #
def convert_sources(sources, opts=None, report=None):
    """SourceLayer のリストを変換する。

    戻り値: (ConvertedLayer のリスト, ConversionReport)
    """
    opts = opts or ConvertOptions()
    report = report or ConversionReport()

    results = []
    for src in sources:
        lrep = report.layer(src.name)
        if src.error:
            lrep.warn("読み込み", src.error)

        try:
            # レンダラから辿れない「概念ごと無い」機能をXMLから洗い出す
            detect_unsupported(src.element, lrep)
            style = convert_source(src, opts, lrep)
            ok = style is not None
        except Exception:
            lrep.error("変換", "変換中に例外が発生しました",
                       traceback.format_exc(limit=3))
            style = default_style(src.kind)
            ok = False

        results.append(ConvertedLayer(src, style, lrep, ok))

    return results, report


def convert_source(src, opts, lrep):
    """1レイヤを変換して style 辞書を返す。"""
    if src.kind in ("Point", "LineString", "Polygon"):
        if src.layer is None:
            lrep.error("変換", "レイヤを構築できなかったため既定値を出力します")
            return default_style(src.kind)
        return convert_vector_layer(src.layer, src.kind, opts, lrep)

    if src.kind == "VectorTile":
        if src.layer is None:
            lrep.error("変換",
                       "ベクトルタイルレイヤを構築できなかったため既定値を出力します")
            style = default_style("VectorTile")
            from .vectortile import extract_tile_url
            style["tile_url"] = extract_tile_url(src.source)
            return style
        return convert_vector_tile_layer(src.layer, opts, lrep,
                                         layer_id=safe_id(src.name))

    if src.kind in ("Raster", "Raster(Tile)"):
        return convert_raster_element(src.element, src.source, src.provider,
                                      opts, lrep)

    lrep.warn("変換", "この種別（{0}）は変換対象外です".format(src.kind))
    return default_style(src.kind)


# ===================================================================== #
def build_payload(layer_name, style):
    """`.fgstyle` のトップレベル構造を組み立てる（定義書 2章）。"""
    return {
        "_format": STYLE_FILE_FORMAT,
        "_version": STYLE_FILE_VERSION,
        "_layer_name": layer_name,
        "geom": style.get("geom", ""),
        "style": style,
    }


def safe_filename(name, used=None):
    """レイヤ名 → ファイル名（本体 `_safe_filename()` と同じ規則）。"""
    safe = _FORBIDDEN.sub("_", name or "").strip().rstrip(". ")
    if not safe:
        safe = "layer"
    candidate = safe + ".fgstyle"
    if used is None:
        return candidate
    index = 2
    while candidate.lower() in used:
        candidate = "{0}_{1}.fgstyle".format(safe, index)
        index += 1
    used.add(candidate.lower())
    return candidate


def safe_id(name):
    """レイヤ名 → MapLibre のソースID（本体 `_safe_id()` と同じ規則）。"""
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", name or "").strip("_")
    return safe or "layer"


def write_fgstyle(path, payload):
    """UTF-8・indent=2 で書き出す（本体の保存形式と同一）。"""
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def write_all(converted, out_dir):
    """ConvertedLayer のリストを一括で書き出す。

    戻り値: [(ConvertedLayer, 出力パス), ...]
    """
    used = set()
    written = []
    for item in converted:
        if item.payload is None:
            continue
        filename = safe_filename(item.name, used)
        path = os.path.join(out_dir, filename)
        write_fgstyle(path, item.payload)
        written.append((item, path))
    return written
