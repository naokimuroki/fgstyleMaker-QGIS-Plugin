# -*- coding: utf-8 -*-
"""入力ファイル（.qgz / .qgs / .qml / .qlr）からスタイル定義を読み出す。

方針
----
実データソースには一切アクセスしない。プロジェクトXMLから `<maplayer>`
要素を取り出し、それを QML 相当の `<qgis>` ドキュメントへ組み替えたうえで、
幾何種別だけを合わせた**空のメモリレイヤ**に `importNamedStyle()` で流し込む。

こうすると
  * データソースが失われた／重い／ネットワーク越しでも読める
  * XMLの構造ではなく QGIS API のレンダラオブジェクトとして扱える
の両方が成り立つ。
"""

import os
import zipfile

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtXml import QDomDocument

from qgis.core import QgsVectorLayer, QgsField

try:
    from qgis.core import QgsVectorTileLayer
except ImportError:      # QGIS 3.14未満
    QgsVectorTileLayer = None


SUPPORTED_EXTENSIONS = (".qgz", ".qgs", ".qml", ".qlr")

_GEOM_BY_CODE = {"0": "Point", "1": "LineString", "2": "Polygon"}
_GEOM_BY_NAME = {
    "point": "Point", "線": "LineString", "line": "LineString",
    "linestring": "LineString", "polygon": "Polygon", "面": "Polygon",
}
_GEOM_BY_SYMBOL = {"marker": "Point", "line": "LineString", "fill": "Polygon"}


class SourceLayer(object):
    """入力ファイルから取り出した1レイヤ分の情報。"""

    __slots__ = ("name", "kind", "layer", "element", "renderer_type",
                 "source", "provider", "error")

    def __init__(self, name, kind, layer=None, element=None,
                 renderer_type="", source="", provider="", error=""):
        self.name = name
        self.kind = kind
        self.layer = layer
        self.element = element
        self.renderer_type = renderer_type
        self.source = source
        self.provider = provider
        self.error = error

    @property
    def is_vector(self):
        return self.kind in ("Point", "LineString", "Polygon")

    @property
    def is_raster(self):
        return self.kind in ("Raster", "Raster(Tile)")

    def __repr__(self):
        return "<SourceLayer {0} {1} {2}>".format(
            self.name, self.kind, self.renderer_type)


# ===================================================================== #
# 入口
# ===================================================================== #
def read_sources(path):
    """ファイルパス → SourceLayer のリスト。

    読み取り自体に失敗した場合は例外を送出する。
    個々のレイヤの失敗は SourceLayer.error に格納する。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError("対応していない拡張子です: {0}".format(ext))

    xml_bytes = _load_xml_bytes(path, ext)
    doc = _parse_xml(xml_bytes, path)
    root = doc.documentElement()

    if ext == ".qml":
        return [_from_style_document(doc, root,
                                     os.path.splitext(os.path.basename(path))[0])]

    elements = _collect_maplayer_elements(root)
    if not elements:
        raise ValueError("レイヤ定義（maplayer要素）が見つかりませんでした。")

    return [_from_maplayer(el) for el in elements]


def _load_xml_bytes(path, ext):
    if ext == ".qgz":
        with zipfile.ZipFile(path, "r") as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".qgs")]
            if not names:
                raise ValueError(".qgz の中に .qgs が見つかりませんでした。")
            return zf.read(names[0])
    with open(path, "rb") as f:
        return f.read()


def _parse_xml(data, path):
    doc = QDomDocument()
    result = doc.setContent(data)
    ok, message = _unpack_set_content(result)
    if not ok:
        raise ValueError("XMLを解析できませんでした（{0}）: {1}".format(
            os.path.basename(path), message))
    return doc


def _unpack_set_content(result):
    """QDomDocument.setContent の戻り値をPyQtのバージョン差を吸収して読む。"""
    if isinstance(result, tuple):
        ok = bool(result[0])
        msg = ""
        if len(result) > 1 and result[1]:
            msg = str(result[1])
            if len(result) > 3:
                msg += " (行{0} 列{1})".format(result[2], result[3])
        return ok, msg
    return bool(result), ""


def _collect_maplayer_elements(root):
    """`<maplayer>` 要素をドキュメント全体から集める（.qgs / .qlr 共通）。"""
    out = []
    nodes = root.elementsByTagName("maplayer")
    for i in range(nodes.count()):
        el = nodes.at(i).toElement()
        if not el.isNull():
            out.append(el)
    return out


# ===================================================================== #
# maplayer → SourceLayer
# ===================================================================== #
def _from_maplayer(el):
    name = _text_of(el, "layername") or el.attribute("name") or "(無名レイヤ)"
    layer_type = (el.attribute("type") or "").lower()
    source = _text_of(el, "datasource") or ""
    provider = _text_of(el, "provider") or ""
    renderer_type = _renderer_type_of(el)

    if layer_type == "raster":
        from .raster import detect_raster_kind
        kind = detect_raster_kind(source, provider)
        return SourceLayer(name, kind, None, el, renderer_type, source, provider)

    if layer_type in ("vector-tile", "vectortile"):
        layer, err = _build_vector_tile_stub(el, name, source)
        return SourceLayer(name, "VectorTile", layer, el,
                           renderer_type or "vector-tile", source, provider, err)

    if layer_type in ("mesh", "point-cloud", "pointcloud", "annotation",
                      "tiled-scene", "group", "plugin"):
        return SourceLayer(name, "Unknown", None, el, layer_type, source, provider,
                           "未対応のレイヤ種別（{0}）です".format(layer_type))

    # ベクタ
    geom = _detect_geometry(el)
    if geom is None:
        return SourceLayer(name, "Unknown", None, el, renderer_type,
                           source, provider, "幾何種別を判別できませんでした")

    layer, err = _build_vector_stub(el, name, geom)
    return SourceLayer(name, geom, layer, el, renderer_type, source, provider, err)


def is_vector_tile_style(root):
    """`<qgis>` / `<maplayer>` がベクトルタイルのスタイルかどうか。

    ベクトルタイルは `<renderer type="basic">` の下に
    `<styles><style layer="…" geometry="…">` を持つ
    （通常のベクタは `<renderer-v2>`、ラスタは `<pipe>`）。
    .qml 単体には `<maplayer type="vector-tile">` が無いため、
    この形で見分けるしかない。
    """
    if root is None or _child_element(root, "renderer-v2") is not None:
        return False
    renderer = _child_element(root, "renderer")
    if renderer is None:
        return False
    styles = _child_element(renderer, "styles")
    if styles is None:
        return False
    style_el = styles.firstChildElement("style")
    if style_el.isNull():
        # スタイル0件でも renderer type="basic" ならVTとみなす
        return (renderer.attribute("type") or "").lower() == "basic"
    return style_el.hasAttribute("layer") or style_el.hasAttribute("geometry")


def _from_style_document(doc, root, name):
    """.qml（root が `<qgis>`）を1レイヤとして扱う。"""
    renderer_type = _renderer_type_of(root)

    if is_vector_tile_style(root):
        layer, err = _build_vector_tile_stub_from_doc(doc, name)
        return SourceLayer(name, "VectorTile", layer, root,
                           renderer_type or "vector-tile", error=err)

    if not _child_element(root, "renderer-v2") and _child_element(root, "pipe"):
        from .raster import detect_raster_kind
        return SourceLayer(name, detect_raster_kind("", ""), None, root,
                           renderer_type or "raster")

    geom = _detect_geometry(root)
    if geom is None:
        return SourceLayer(name, "Unknown", None, root, renderer_type,
                           error="幾何種別を判別できませんでした")

    layer = QgsVectorLayer("{0}?crs=EPSG:4326".format(geom), name, "memory")
    _add_stub_fields(layer, _field_names(root))
    ok, err = _import_style(layer, doc.cloneNode(True).toDocument())
    return SourceLayer(name, geom, layer, root, renderer_type,
                       error="" if ok else err)


# --------------------------------------------------------------------- #
def _build_vector_stub(el, name, geom):
    layer = QgsVectorLayer("{0}?crs=EPSG:4326".format(geom), name, "memory")
    if not layer.isValid():
        return None, "メモリレイヤを作成できませんでした"
    _add_stub_fields(layer, _field_names(el))
    doc = _style_document_from(el)
    ok, err = _import_style(layer, doc)
    return layer, "" if ok else err


#: データソースを持たない .qml を読むためのダミーURI（通信は発生しない）
_VT_STUB_URI = "type=xyz&url=https://example.invalid/{z}/{x}/{y}.pbf"


def _new_vector_tile_layer(uri, name):
    if QgsVectorTileLayer is None:
        return None, "このQGISはベクトルタイルに対応していません"
    try:
        return QgsVectorTileLayer(uri or _VT_STUB_URI, name), ""
    except Exception as exc:
        return None, "ベクトルタイルレイヤを作成できませんでした: {0}".format(exc)


def _build_vector_tile_stub(el, name, source):
    layer, err = _new_vector_tile_layer(source, name)
    if layer is None:
        return None, err
    ok, err = _import_style(layer, _style_document_from(el))
    return layer, "" if ok else err


def _build_vector_tile_stub_from_doc(doc, name):
    """.qml（ドキュメントそのものがスタイル）→ ベクトルタイルのスタブ。"""
    layer, err = _new_vector_tile_layer("", name)
    if layer is None:
        return None, err
    ok, err = _import_style(layer, doc.cloneNode(True).toDocument())
    return layer, "" if ok else err


def _style_document_from(el):
    """`<maplayer>` → QML相当の `<qgis>` ドキュメント。

    maplayer の子要素をそのままルート直下へ移し、縮尺依存表示などの
    属性をルートへコピーする。QGISの readSymbology / readStyle は
    タグ名で子要素を探すため、この組み替えで素直に読み込める。
    """
    doc = QDomDocument()
    root = doc.createElement("qgis")
    doc.appendChild(root)

    for attr in ("version", "styleCategories", "hasScaleBasedVisibilityFlag",
                 "minScale", "maxScale", "symbologyReferenceScale",
                 "labelsEnabled", "readOnly", "simplifyDrawingHints",
                 "simplifyDrawingTol", "simplifyLocal", "simplifyMaxScale",
                 "simplifyAlgorithm", "autoRefreshTime", "autoRefreshMode"):
        if el.hasAttribute(attr):
            root.setAttribute(attr, el.attribute(attr))
    if not root.hasAttribute("styleCategories"):
        root.setAttribute("styleCategories", "AllStyleCategories")

    child = el.firstChild()
    while not child.isNull():
        if child.isElement():
            root.appendChild(doc.importNode(child, True))
        child = child.nextSibling()

    return doc


def _import_style(layer, doc):
    """importNamedStyle をPyQGISの戻り値差異を吸収して呼ぶ。"""
    try:
        result = layer.importNamedStyle(doc)
    except TypeError:
        try:
            result = layer.importNamedStyle(doc, "")
        except Exception as exc:
            return False, "スタイルを読み込めませんでした: {0}".format(exc)
    except Exception as exc:
        return False, "スタイルを読み込めませんでした: {0}".format(exc)

    if isinstance(result, tuple):
        ok = bool(result[0])
        msg = str(result[1]) if len(result) > 1 and result[1] else ""
        return ok, msg
    return bool(result), ""


def _add_stub_fields(layer, names):
    """レンダラ／ラベルが参照する属性名だけを持つ空フィールドを足す。"""
    if not names:
        return
    try:
        provider = layer.dataProvider()
        provider.addAttributes([QgsField(n, QVariant.String) for n in names])
        layer.updateFields()
    except Exception:
        pass


# ===================================================================== #
# XMLヘルパー
# ===================================================================== #
def _child_element(el, tag):
    if el is None:
        return None
    e = el.firstChildElement(tag)
    return None if e.isNull() else e


def _text_of(el, tag):
    e = _child_element(el, tag)
    return e.text().strip() if e is not None else ""


def _renderer_type_of(el):
    r = _child_element(el, "renderer-v2")
    if r is not None:
        return r.attribute("type") or "unknown"
    pipe = _child_element(el, "pipe")
    rr = _child_element(pipe, "rasterrenderer") if pipe is not None else None
    if rr is None:
        rr = _child_element(el, "rasterrenderer")
    if rr is not None:
        return rr.attribute("type") or "raster"
    return ""


def _detect_geometry(el):
    """幾何種別を段階的に判定する。"""
    # 1) <layerGeometryType>0|1|2</layerGeometryType>（QML・QGS共通）
    code = _text_of(el, "layerGeometryType")
    if code in _GEOM_BY_CODE:
        return _GEOM_BY_CODE[code]

    # 2) maplayer の geometry 属性
    name = (el.attribute("geometry") or "").strip().lower()
    if name in _GEOM_BY_NAME:
        return _GEOM_BY_NAME[name]

    # 3) レンダラ内の最初の <symbol type="marker|line|fill">
    symbols = el.elementsByTagName("symbol")
    for i in range(symbols.count()):
        stype = symbols.at(i).toElement().attribute("type", "").lower()
        if stype in _GEOM_BY_SYMBOL:
            return _GEOM_BY_SYMBOL[stype]

    # 4) WKB型（<wkbType>）
    wkb = _text_of(el, "wkbType").lower()
    for key, val in (("point", "Point"), ("line", "LineString"),
                     ("polygon", "Polygon")):
        if key in wkb:
            return val

    return None


def _field_names(el):
    """`<fieldConfiguration>` などから属性名を集める（重複除去・順序保持）。"""
    names = []
    seen = set()

    for container_tag, item_tag, attr in (
            ("fieldConfiguration", "field", "name"),
            ("aliases", "alias", "name"),
            ("expressionfields", "field", "name")):
        container = _child_element(el, container_tag)
        if container is None:
            continue
        items = container.elementsByTagName(item_tag)
        for i in range(items.count()):
            n = items.at(i).toElement().attribute(attr, "").strip()
            if n and n not in seen:
                seen.add(n)
                names.append(n)

    return names
