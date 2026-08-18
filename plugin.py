# -*- coding: utf-8 -*-
"""fgstyle Maker のQGIS連携部（メニュー／ツールバー登録とダイアログ起動）。"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

PLUGIN_DIR = os.path.dirname(__file__)
MENU_TITLE = "fgstyle Maker"


class FgstyleMakerPlugin:
    """QGISプラグインのエントリポイント。"""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    # ------------------------------------------------------------------ #
    def initGui(self):  # noqa: N802
        icon_path = os.path.join(PLUGIN_DIR, "icons", "fgstyle_maker.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        self.action = QAction(icon, "fgstyle Maker…", self.iface.mainWindow())
        self.action.setToolTip(
            "QGISプロジェクト・スタイルファイルから .fgstyle を生成します"
        )
        self.action.triggered.connect(self.run)

        self.iface.addPluginToMenu(MENU_TITLE, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu(MENU_TITLE, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    # ------------------------------------------------------------------ #
    def run(self):
        from .dialog import FgstyleMakerDialog

        if self.dialog is None:
            self.dialog = FgstyleMakerDialog(self.iface, self.iface.mainWindow())
            self.dialog.setAttribute(Qt.WA_DeleteOnClose, False)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
