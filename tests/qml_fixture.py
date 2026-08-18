# -*- coding: utf-8 -*-
"""QMLからレンダラ相当のダミーオブジェクトを組み立てるテスト用ローダ。

QGIS本体が無い環境で converter のロジック（式パース・ルール生成・
色/幅の抽出・レポート）を実データで検証するために使う。
QGIS上では reader.py が本物の QgsVectorLayer を作るので、これは
あくまでテスト専用。
"""

import xml.etree.ElementTree as ET

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


# --------------------------------------------------------------------- #
def parse_qgis_color(text):
    """'255,211,250,255,rgb:1,0.82,0.98,1' → QColor"""
    if not text:
        return QColor()
    parts = str(text).split(",")
    try:
        vals = [int(float(p)) for p in parts[:4]]
    except (TypeError, ValueError):
        return QColor()
    while len(vals) < 4:
        vals.append(255)
    return QColor(vals[0], vals[1], vals[2], vals[3])


_PEN_STYLE = {
    "solid": Qt.SolidLine, "dash": Qt.DashLine, "dot": Qt.DotLine,
    "dash dot": Qt.DashDotLine, "dash dot dot": Qt.DashDotDotLine,
    "no": Qt.NoPen,
}
_BRUSH_STYLE = {
    "solid": Qt.SolidPattern, "no": Qt.NoBrush,
    "horizontal": Qt.HorPattern, "vertical": Qt.VerPattern,
    "cross": Qt.CrossPattern, "b_diagonal": Qt.BDiagPattern,
    "f_diagonal": Qt.FDiagPattern,
}


class _DataDefined(object):
    def hasActiveProperties(self):
        return False


class SymbolLayer(object):
    """QgsSymbolLayer 相当。クラス名で分岐されるため type 名を合わせる。"""

    def __init__(self, cls_name, opts):
        self._opts = opts
        self.__class__ = type(cls_name, (SymbolLayer,), {})

    # 共通
    def dataDefinedProperties(self):
        return _DataDefined()

    def _opt(self, name, default=None):
        return self._opts.get(name, default)

    def _num(self, name, default=0.0):
        try:
            return float(self._opts.get(name, default))
        except (TypeError, ValueError):
            return default

    # 塗り
    def fillColor(self):
        return parse_qgis_color(self._opt("color"))

    def color(self):
        return parse_qgis_color(self._opt("color"))

    def color2(self):
        return parse_qgis_color(self._opt("color2"))

    def brushStyle(self):
        return _BRUSH_STYLE.get(self._opt("style", "solid"), Qt.SolidPattern)

    # 線（QgsLineSymbolLayer.width() / widthUnit() 相当）
    def width(self):
        if "line_width" not in self._opts:
            return None
        return self._num("line_width", 0.0)

    def widthUnit(self):
        return self._opt("line_width_unit", "MM")

    # 線・縁取り
    def strokeColor(self):
        return parse_qgis_color(self._opt("outline_color") or self._opt("line_color"))

    def strokeWidth(self):
        return self._num("outline_width", self._num("line_width", 0.0))

    def strokeWidthUnit(self):
        return self._opt("outline_width_unit",
                         self._opt("line_width_unit", "MM"))

    def strokeStyle(self):
        return _PEN_STYLE.get(
            self._opt("outline_style", self._opt("line_style", "solid")),
            Qt.SolidLine)

    def penStyle(self):
        return _PEN_STYLE.get(self._opt("line_style", "solid"), Qt.SolidLine)

    def useCustomDashPattern(self):
        return str(self._opt("use_custom_dash", "0")) == "1"

    def customDashVector(self):
        """QGISは "6;3" のようにセミコロン区切りで持つ。"""
        raw = self._opt("customdash", "") or ""
        out = []
        for part in str(raw).replace(",", ";").split(";"):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError:
                return []
        return out

    def customDashPatternUnit(self):
        return self._opt("customdash_unit", "MM")

    def dashPatternOffset(self):
        return self._num("dash_pattern_offset", 0.0)

    def offset(self):
        try:
            return float(str(self._opt("offset", "0")).split(",")[0])
        except (TypeError, ValueError):
            return 0.0

    # マーカー
    def shape(self):
        return self._opt("name", "circle")


class Symbol(object):
    """QgsSymbol 相当。"""

    def __init__(self, element):
        self._type = element.get("type", "fill")
        self._alpha = float(element.get("alpha", "1") or 1)
        self._layers = []
        for layer_el in element.findall("layer"):
            opts = {}
            for opt in layer_el.iter("Option"):
                name = opt.get("name")
                if name is not None and opt.get("value") is not None:
                    opts.setdefault(name, opt.get("value"))
            self._layers.append(SymbolLayer(
                "Qgs{0}SymbolLayer".format(layer_el.get("class", "Simple")),
                opts))

    def symbolLayerCount(self):
        return len(self._layers)

    def symbolLayer(self, i):
        return self._layers[i]

    def opacity(self):
        return self._alpha

    def color(self):
        if not self._layers:
            return QColor()
        sl = self._layers[0]
        if self._type == "line":
            return parse_qgis_color(sl._opt("line_color"))
        return parse_qgis_color(sl._opt("color"))

    # line
    #   QgsLineSymbol は width() を持つが **widthUnit() ゲッターは無い**
    #   （setWidthUnit() のみ）。converter が symbol 側の単位に頼っていないか
    #   をここで担保するため、あえて widthUnit() を定義しない。
    def width(self):
        return self._layers[0]._num("line_width", 0.0) if self._layers else 0.0

    # marker
    def size(self):
        return self._layers[0]._num("size", 2.0) if self._layers else 2.0

    def sizeUnit(self):
        return self._layers[0]._opt("size_unit", "MM") if self._layers else "MM"

    def angle(self):
        return self._layers[0]._num("angle", 0.0) if self._layers else 0.0


# --------------------------------------------------------------------- #
class Rule(object):
    def __init__(self, element, symbols):
        self._filter = element.get("filter", "")
        self._label = element.get("label", "")
        self._symbol = symbols.get(element.get("symbol"))
        self._children = [Rule(c, symbols) for c in element.findall("rule")]

    def filterExpression(self):
        return self._filter

    def label(self):
        return self._label

    def symbol(self):
        return self._symbol

    def children(self):
        return self._children

    def active(self):
        return True

    def isElse(self):
        return self._filter.strip().lower() in ("else", "")


class RuleBasedRenderer(object):
    def __init__(self, element, symbols):
        rules_el = element.find("rules")
        self._root = _Root([Rule(r, symbols)
                            for r in (rules_el if rules_el is not None else [])])

    def type(self):
        return "RuleRenderer"

    def rootRule(self):
        return self._root


class _Root(object):
    def __init__(self, children):
        self._children = children

    def children(self):
        return self._children


class Category(object):
    def __init__(self, value, symbol, label="", render=True):
        self._value, self._symbol = value, symbol
        self._label, self._render = label, render

    def value(self):
        return self._value

    def symbol(self):
        return self._symbol

    def label(self):
        return self._label

    def renderState(self):
        return self._render


class CategorizedRenderer(object):
    def __init__(self, attribute, categories, source=None):
        self._attr, self._cats, self._source = attribute, categories, source

    def type(self):
        return "categorizedSymbol"

    def classAttribute(self):
        return self._attr

    def categories(self):
        return self._cats

    def sourceSymbol(self):
        return self._source


class Range(object):
    def __init__(self, lower, upper, symbol, label="", render=True):
        self._lo, self._hi = lower, upper
        self._symbol, self._label, self._render = symbol, label, render

    def lowerValue(self):
        return self._lo

    def upperValue(self):
        return self._hi

    def symbol(self):
        return self._symbol

    def label(self):
        return self._label

    def renderState(self):
        return self._render


class GraduatedRenderer(object):
    def __init__(self, attribute, ranges, source=None):
        self._attr, self._ranges, self._source = attribute, ranges, source

    def type(self):
        return "graduatedSymbol"

    def classAttribute(self):
        return self._attr

    def ranges(self):
        return self._ranges

    def sourceSymbol(self):
        return self._source


class SingleRenderer(object):
    def __init__(self, symbol):
        self._symbol = symbol

    def type(self):
        return "singleSymbol"

    def symbol(self):
        return self._symbol


# --------------------------------------------------------------------- #
class FakeLayer(object):
    """QgsVectorLayer 相当（converter が触るメソッドだけ）。"""

    def __init__(self, renderer, opacity=1.0, scale=None, labeling=None):
        self._renderer = renderer
        self._opacity = opacity
        self._scale = scale        # (minScale, maxScale) or None
        self._labeling = labeling

    def renderer(self):
        return self._renderer

    def opacity(self):
        return self._opacity

    def hasScaleBasedVisibility(self):
        return self._scale is not None

    def minimumScale(self):
        return self._scale[0] if self._scale else 0

    def maximumScale(self):
        return self._scale[1] if self._scale else 0

    def labelsEnabled(self):
        return self._labeling is not None

    def labeling(self):
        return self._labeling


GEOM_BY_CODE = {"0": "Point", "1": "LineString", "2": "Polygon"}


def load_qml(path):
    """QMLファイル → (FakeLayer, geom)。"""
    root = ET.parse(path).getroot()
    geom = GEOM_BY_CODE.get((root.findtext("layerGeometryType") or "").strip(),
                            "Polygon")

    rd = root.find("renderer-v2")
    symbols = {}
    syms_el = rd.find("symbols")
    if syms_el is not None:
        for s in syms_el:
            symbols[s.get("name")] = Symbol(s)

    rtype = rd.get("type")
    if rtype == "RuleRenderer":
        renderer = RuleBasedRenderer(rd, symbols)
    elif rtype == "singleSymbol":
        renderer = SingleRenderer(list(symbols.values())[0] if symbols else None)
    else:
        raise NotImplementedError("テストローダ未対応: " + str(rtype))

    try:
        opacity = float(root.findtext("layerOpacity") or 1.0)
    except (TypeError, ValueError):
        opacity = 1.0

    scale = None
    if root.get("hasScaleBasedVisibilityFlag") == "1":
        scale = (float(root.get("minScale") or 0), float(root.get("maxScale") or 0))

    return FakeLayer(renderer, opacity, scale), geom
