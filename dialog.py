# -*- coding: utf-8 -*-
"""fgstyle Maker のダイアログ。"""

import os
import traceback

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QColorDialog, QDialog,
                                 QFileDialog, QHBoxLayout, QMessageBox,
                                 QTableWidgetItem, QWidget)

from .converter.core import convert_sources, safe_filename, write_fgstyle
from .converter.options import ConvertOptions
from .converter.reader import read_sources
from .converter.report import Level

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "dialog.ui"))

INPUT_FILTER = (
    "QGISプロジェクト・スタイル (*.qgz *.qgs *.qml *.qlr);;"
    "QGISプロジェクト (*.qgz *.qgs);;"
    "スタイル定義 (*.qml *.qlr);;"
    "すべてのファイル (*)"
)

# ForestGeo Studio テーマの配色（theme.qss と揃える）
THEME = {
    "deep": "#43A28C", "mid": "#6ABC6E", "light": "#BEDFC2",
    "cream": "#FFFDF6", "yellow": "#FFFCDA",
    "text": "#1e3a2f", "sub": "#4a7c65",
}

_LEVEL_COLOR = {
    Level.ERROR: "#b71c1c",
    Level.WARN: "#ef6c00",
    Level.APPROX: THEME["sub"],
    Level.INFO: THEME["deep"],
}

#: 「該当なしの既定色」に並べる色（QGISの標準色＋グレー系）
DEFAULT_COLOR_CHOICES = (
    ("薄いグレー", "#cccccc"),
    ("グレー", "#9e9e9e"),
    ("濃いグレー", "#616161"),
    ("生成り", "#f0ece0"),
    ("薄い青", "#bcd7e8"),
    ("薄い緑", "#c8e6c9"),
    ("薄い黄", "#fff2b2"),
    ("薄い赤", "#f2c4c4"),
    ("白", "#ffffff"),
    ("黒", "#000000"),
)

COL_OUTPUT = 0
COL_NAME = 1
COL_KIND = 2
COL_RENDERER = 3
COL_RESULT = 4


class FgstyleMakerDialog(QDialog, FORM_CLASS):
    """QGISのスタイル定義を .fgstyle へ変換するダイアログ。"""

    def __init__(self, iface, parent=None):
        super(FgstyleMakerDialog, self).__init__(parent)
        self.setupUi(self)
        self.iface = iface

        self._sources = []      # SourceLayer のリスト
        self._converted = []    # ConvertedLayer のリスト
        self._report = None

        self._apply_theme()

        mono = QFont("Monospace")
        mono.setStyleHint(QFont.TypeWriter)
        mono.setPointSize(9)
        self.txtPreview.setFont(mono)

        self.tblLayers.setColumnCount(5)
        self.tblLayers.setHorizontalHeaderLabels(
            ["出力", "レイヤ名", "種別", "レンダラ", "変換結果"])
        self.tblLayers.horizontalHeader().setStretchLastSection(True)

        self.btnBrowse.clicked.connect(self._browse_input)
        self.btnLoad.clicked.connect(self._load_input)
        self.btnOutDir.clicked.connect(self._browse_outdir)
        self.btnExport.clicked.connect(self._export)
        self.btnSaveReport.clicked.connect(self._save_report)
        self.btnSelectAll.clicked.connect(lambda: self._set_all_checked(True))
        self.btnSelectNone.clicked.connect(lambda: self._set_all_checked(False))
        self.tblLayers.itemSelectionChanged.connect(self._on_layer_selected)
        self.buttonBox.rejected.connect(self.close)

        self._setup_default_color()

        # 設定を変えたら再変換する
        self.spinMaxRules.valueChanged.connect(self._reconvert)
        self.spinMinLineWidth.valueChanged.connect(self._reconvert)
        self.spinMinDashGap.valueChanged.connect(self._reconvert)
        self.cmbDefaultColor.currentIndexChanged.connect(
            self._on_default_color_changed)
        for widget in (self.chkScaleVisibility, self.chkLabeling,
                       self.chkRuleLabels, self.chkCloseGaps,
                       self.chkNormalizeValues):
            widget.toggled.connect(self._reconvert)

    # ----------------------------------------------------------------- #
    def _apply_theme(self):
        """ForestGeo Studio 本体と同じ配色（theme.qss）を適用する。"""
        path = os.path.join(os.path.dirname(__file__), "theme.qss")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception:
            # テーマが読めなくても機能には影響しないので黙って既定の外観にする
            self._log_theme_failure(path)

    def _log_theme_failure(self, path):
        try:
            print("[fgstyle Maker] テーマを読み込めませんでした: " + path)
        except Exception:
            pass

    def _setup_default_color(self):
        """「該当なしの既定色」コンボへ色見本を流し込む。"""
        combo = self.cmbDefaultColor
        combo.blockSignals(True)
        combo.clear()
        for name, code in DEFAULT_COLOR_CHOICES:
            pixmap = QPixmap(48, 16)
            pixmap.fill(QColor(code))
            combo.addItem(QIcon(pixmap), "{0}  {1}".format(name, code), code)
        combo.addItem("その他の色…", "")
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        combo.setToolTip(
            "どのルールにも該当しない地物に使う色です。QGISは該当なしを"
            "描画しませんが、MapLibre の式は必ず既定値へフォールバックする"
            "ため、この色で描かれます。")

    def _on_default_color_changed(self, index):
        """「その他の色…」ならカラーダイアログを開く。"""
        combo = self.cmbDefaultColor
        if combo.itemData(index) == "":
            color = QColorDialog.getColor(
                QColor(self._default_color_code() or "#cccccc"), self,
                "該当なしの既定色")
            if color.isValid():
                code = color.name()
                pixmap = QPixmap(48, 16)
                pixmap.fill(color)
                combo.blockSignals(True)
                combo.insertItem(index, QIcon(pixmap),
                                 "指定色  {0}".format(code), code)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
            else:
                combo.blockSignals(True)
                combo.setCurrentIndex(0)
                combo.blockSignals(False)
        self._reconvert()

    def _default_color_code(self):
        code = self.cmbDefaultColor.currentData()
        return code if code else "#cccccc"

    # ================================================================= #
    # 設定
    # ================================================================= #
    def _options(self):
        # dpi・基準緯度・基準ズーム・ズーム丸めはUIから外して固定値にした。
        # （mm→px換算や縮尺→ズーム換算には引き続き使われる）
        return ConvertOptions(
            convert_scale_visibility=self.chkScaleVisibility.isChecked(),
            convert_labeling=self.chkLabeling.isChecked(),
            default_color=self._default_color_code(),
            emit_rule_labels=self.chkRuleLabels.isChecked(),
            close_numeric_gaps=self.chkCloseGaps.isChecked(),
            normalize_values=self.chkNormalizeValues.isChecked(),
            min_line_width=self.spinMinLineWidth.value(),
            min_dash_gap=self.spinMinDashGap.value(),
            max_rules=self.spinMaxRules.value(),
        )

    # ================================================================= #
    # 入力
    # ================================================================= #
    def _browse_input(self):
        start = self.txtInput.text().strip() or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "QGISプロジェクト／スタイルファイルを選択", start, INPUT_FILTER)
        if path:
            self.txtInput.setText(path)
            if not self.txtOutDir.text().strip():
                self.txtOutDir.setText(os.path.dirname(path))
            self._load_input()

    def _browse_outdir(self):
        start = self.txtOutDir.text().strip() or ""
        path = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択", start)
        if path:
            self.txtOutDir.setText(path)

    def _load_input(self):
        path = self.txtInput.text().strip()
        if not path:
            QMessageBox.information(self, "fgstyle Maker",
                                    "入力ファイルを指定してください。")
            return
        if not os.path.exists(path):
            QMessageBox.warning(self, "fgstyle Maker",
                                "ファイルが見つかりません。\n" + path)
            return

        self.setEnabled(False)
        try:
            self._sources = read_sources(path)
        except Exception as exc:
            self.setEnabled(True)
            self._sources = []
            self._converted = []
            self.tblLayers.setRowCount(0)
            QMessageBox.critical(
                self, "fgstyle Maker",
                "読み込みに失敗しました。\n\n{0}".format(exc))
            self._status("読み込み失敗: {0}".format(exc), Level.ERROR)
            return
        finally:
            self.setEnabled(True)

        if not self._sources:
            self._status("レイヤが見つかりませんでした。", Level.WARN)
            return

        self._convert()

    # ================================================================= #
    # 変換
    # ================================================================= #
    def _reconvert(self):
        if self._sources:
            self._convert(keep_selection=True)

    def _convert(self, keep_selection=False):
        row = self.tblLayers.currentRow() if keep_selection else 0
        checked = self._checked_names() if keep_selection else None

        self.setEnabled(False)
        try:
            self._converted, self._report = convert_sources(
                self._sources, self._options())
        except Exception:
            QMessageBox.critical(
                self, "fgstyle Maker",
                "変換中にエラーが発生しました。\n\n" + traceback.format_exc(limit=5))
            return
        finally:
            self.setEnabled(True)

        self._fill_table(checked)
        self.txtReport.setHtml(self._report.to_html())

        if 0 <= row < self.tblLayers.rowCount():
            self.tblLayers.selectRow(row)
        elif self.tblLayers.rowCount():
            self.tblLayers.selectRow(0)

        errors = self._report.count(Level.ERROR)
        warns = self._report.count(Level.WARN)
        level = Level.ERROR if errors else (Level.WARN if warns else Level.INFO)
        message = ("{0} レイヤを変換しました（エラー {1} / 警告 {2} / 近似 {3}）。"
                   "出力先フォルダを指定して書き出してください。".format(
                       len(self._converted), errors, warns,
                       self._report.count(Level.APPROX)))
        self._status(message, level)

    # ================================================================= #
    # テーブル
    # ================================================================= #
    def _fill_table(self, keep_checked=None):
        self.tblLayers.blockSignals(True)
        self.tblLayers.setRowCount(0)

        for item in self._converted:
            row = self.tblLayers.rowCount()
            self.tblLayers.insertRow(row)

            holder = QWidget()
            layout = QHBoxLayout(holder)
            layout.setAlignment(Qt.AlignCenter)
            layout.setContentsMargins(0, 0, 0, 0)
            chk = QCheckBox()
            default_on = item.kind != "Unknown"
            if keep_checked is not None:
                chk.setChecked(item.name in keep_checked)
            else:
                chk.setChecked(default_on)
            chk.setEnabled(item.payload is not None)
            layout.addWidget(chk)
            self.tblLayers.setCellWidget(row, COL_OUTPUT, holder)

            self._set_cell(row, COL_NAME, item.name)
            self._set_cell(row, COL_KIND, item.kind)
            self._set_cell(row, COL_RENDERER, item.source.renderer_type or "—")

            summary = item.report.summary()
            cell = self._set_cell(row, COL_RESULT, summary)
            worst = item.report.worst_level()
            if worst in (Level.ERROR, Level.WARN, Level.APPROX):
                cell.setForeground(QBrush(QColor(_LEVEL_COLOR[worst])))

        self.tblLayers.resizeColumnsToContents()
        self.tblLayers.blockSignals(False)

    def _set_cell(self, row, col, text):
        cell = QTableWidgetItem(str(text))
        cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
        self.tblLayers.setItem(row, col, cell)
        return cell

    def _checkbox_at(self, row):
        holder = self.tblLayers.cellWidget(row, COL_OUTPUT)
        return holder.findChild(QCheckBox) if holder else None

    def _checked_names(self):
        names = set()
        for row in range(self.tblLayers.rowCount()):
            chk = self._checkbox_at(row)
            if chk and chk.isChecked():
                cell = self.tblLayers.item(row, COL_NAME)
                if cell:
                    names.add(cell.text())
        return names

    def _set_all_checked(self, checked):
        for row in range(self.tblLayers.rowCount()):
            chk = self._checkbox_at(row)
            if chk and chk.isEnabled():
                chk.setChecked(checked)

    def _on_layer_selected(self):
        row = self.tblLayers.currentRow()
        if row < 0 or row >= len(self._converted):
            self.txtPreview.setPlainText("")
            return
        item = self._converted[row]
        if item.payload is None:
            self.txtPreview.setPlainText("（このレイヤは変換できませんでした）")
            return
        self.txtPreview.setPlainText(item.to_json())

    # ================================================================= #
    # 出力
    # ================================================================= #
    def _export(self):
        if not self._converted:
            QMessageBox.information(self, "fgstyle Maker",
                                    "先にファイルを読み込んでください。")
            return

        out_dir = self.txtOutDir.text().strip()
        if not out_dir:
            QMessageBox.information(self, "fgstyle Maker",
                                    "出力先フォルダを指定してください。")
            return
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir)
            except OSError as exc:
                QMessageBox.warning(
                    self, "fgstyle Maker",
                    "出力先フォルダを作成できませんでした。\n{0}".format(exc))
                return

        targets = []
        for row in range(self.tblLayers.rowCount()):
            chk = self._checkbox_at(row)
            if chk and chk.isChecked() and row < len(self._converted):
                if self._converted[row].payload is not None:
                    targets.append(self._converted[row])

        if not targets:
            QMessageBox.information(self, "fgstyle Maker",
                                    "書き出すレイヤを選択してください。")
            return

        used = set()
        written = []
        failed = []
        for item in targets:
            filename = safe_filename(item.name, used)
            path = os.path.join(out_dir, filename)
            try:
                write_fgstyle(path, item.payload)
                written.append(path)
            except Exception as exc:
                failed.append("{0}: {1}".format(item.name, exc))

        message = "{0} 件の .fgstyle を書き出しました。\n{1}".format(
            len(written), out_dir)
        if failed:
            message += "\n\n失敗 {0} 件:\n".format(len(failed)) + "\n".join(failed)
            QMessageBox.warning(self, "fgstyle Maker", message)
        else:
            QMessageBox.information(self, "fgstyle Maker", message)

        self._status(message.replace("\n", " "),
                     Level.WARN if failed else Level.INFO)

    def _save_report(self):
        if self._report is None:
            QMessageBox.information(self, "fgstyle Maker",
                                    "レポートがありません。")
            return
        start = os.path.join(self.txtOutDir.text().strip() or "",
                             "fgstyle_conversion_report.md")
        path, _ = QFileDialog.getSaveFileName(
            self, "変換レポートを保存", start,
            "Markdown (*.md);;テキスト (*.txt);;すべてのファイル (*)")
        if not path:
            return
        try:
            body = (self._report.to_text() if path.lower().endswith(".txt")
                    else self._report.to_markdown())
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
        except Exception as exc:
            QMessageBox.warning(self, "fgstyle Maker",
                                "レポートを保存できませんでした。\n{0}".format(exc))
            return
        QMessageBox.information(self, "fgstyle Maker",
                                "レポートを保存しました。\n" + path)

    # ================================================================= #
    def _status(self, text, level=Level.INFO):
        self.lblStatus.setText(text)
        self.lblStatus.setStyleSheet(
            "color:{0};".format(_LEVEL_COLOR.get(level, "#333333")))
