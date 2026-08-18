# -*- coding: utf-8 -*-
"""QGIS外でconverterを検証するための最小スタブ。

`qgis.PyQt.*` は実物のPyQt5へ委譲し、`qgis.core` のうち converter が
実際に触れるものだけを用意する。QGIS上では当然このモジュールは使わない。
"""

import sys
import types


def install():
    """sys.modules に qgis / qgis.core / qgis.PyQt を差し込む。"""
    if "qgis.core" in sys.modules:
        return

    qgis = types.ModuleType("qgis")
    core = types.ModuleType("qgis.core")

    class QgsUnitTypes(object):
        """encodeUnit() は本物と同じ文字列コードを返す。

        スタブでは単位そのものを文字列で持ち回るため恒等関数でよい。
        """
        RenderMillimeters = "MM"
        RenderPoints = "Point"
        RenderPixels = "Pixel"
        RenderInches = "Inch"
        RenderMapUnits = "MapUnit"
        RenderMetersInMapUnits = "RenderMetersInMapUnit"
        RenderPercentage = "Percentage"

        @staticmethod
        def encodeUnit(unit):
            return str(unit) if unit is not None else "Pixel"

    class QgsSimpleMarkerSymbolLayerBase(object):
        @staticmethod
        def encodeShape(shape):
            return str(shape)

    core.QgsUnitTypes = QgsUnitTypes
    core.QgsSimpleMarkerSymbolLayerBase = QgsSimpleMarkerSymbolLayerBase

    # reader.py は QGIS 本体が要る。テストでは XML ヘルパーのみ使うため
    # 名前だけ用意しておく。
    class _Unavailable(object):
        def __init__(self, *args, **kwargs):
            raise RuntimeError("QGIS環境でのみ利用できます")

    core.QgsVectorLayer = _Unavailable
    core.QgsVectorTileLayer = _Unavailable
    core.QgsField = _Unavailable
    core.QgsReadWriteContext = _Unavailable

    pyqt = types.ModuleType("qgis.PyQt")
    import PyQt5
    import PyQt5.QtCore
    import PyQt5.QtGui
    import PyQt5.QtXml

    pyqt.QtCore = PyQt5.QtCore
    pyqt.QtGui = PyQt5.QtGui
    pyqt.QtXml = PyQt5.QtXml

    qgis.core = core
    qgis.PyQt = pyqt

    sys.modules["qgis"] = qgis
    sys.modules["qgis.core"] = core
    sys.modules["qgis.PyQt"] = pyqt
    sys.modules["qgis.PyQt.QtCore"] = PyQt5.QtCore
    sys.modules["qgis.PyQt.QtGui"] = PyQt5.QtGui
    sys.modules["qgis.PyQt.QtXml"] = PyQt5.QtXml
    _ = PyQt5
