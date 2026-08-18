# -*- coding: utf-8 -*-
"""
fgstyle Maker — QGISのスタイル定義を ForestGeo Studio の .fgstyle に変換するプラグイン。
"""


def classFactory(iface):  # noqa: N802  (QGISプラグインAPIの規定名)
    from .plugin import FgstyleMakerPlugin
    return FgstyleMakerPlugin(iface)
