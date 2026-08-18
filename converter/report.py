# -*- coding: utf-8 -*-
"""変換時の情報・警告を集めるレポート。"""

import datetime


class Level(object):
    INFO = "INFO"
    APPROX = "APPROX"   # 近似変換した（見た目が変わる可能性あり）
    WARN = "WARN"       # 変換できず既定値になった
    ERROR = "ERROR"     # 変換自体が失敗した

    ORDER = {INFO: 0, APPROX: 1, WARN: 2, ERROR: 3}
    LABEL = {
        INFO: "情報",
        APPROX: "近似",
        WARN: "警告",
        ERROR: "エラー",
    }
    #: 区分ごとの「利用者が何をすべきか」
    ACTION = {
        INFO: "対応不要（プラグイン側で対処済み）",
        APPROX: "確認推奨（近似したので見た目が少し変わる）",
        WARN: "対処が必要（QGIS側の作り直し、または本体側の対応）",
        ERROR: "変換失敗（既定値が出力されている）",
    }


class Entry(object):
    __slots__ = ("layer", "level", "category", "message", "detail", "count")

    def __init__(self, layer, level, category, message, detail=""):
        self.layer = layer
        self.level = level
        self.category = category
        self.message = message
        self.detail = detail
        self.count = 1          # 同一内容がまとめられた件数

    @property
    def text(self):
        """件数つきの本文（2件以上なら「（他N件）」を付ける）。"""
        if self.count > 1:
            return "{0}（他{1}件）".format(self.message, self.count - 1)
        return self.message

    def __repr__(self):
        return "<Entry {0} {1} {2}>".format(self.layer, self.level, self.message)


# 以前は「この出力を反映するには本体にパッチA〜Dが必要」と表示していたが、
# 現行の ForestGeo Studio 本体はそれらを取り込み済みで、利用者にとっては
# 意味の分からない警告でしかないため表示をやめた。
# 呼び出し側（converter）は need_patch() を呼び続けてよい（記録のみ）。


class LayerReport(object):
    """1レイヤ分のレポート。converter からはこのオブジェクトに書き込む。"""

    def __init__(self, layer_name, parent=None):
        self.layer_name = layer_name
        self.entries = []
        self.patches = set()
        self._parent = parent
        self._seen = {}

    def need_patch(self, key):
        """このレイヤの出力が必要とする本体パッチを記録する。"""
        self.patches.add(key)
        if self._parent is not None:
            self._parent.patches.add(key)

    def _add(self, level, category, message, detail=""):
        # 同じ内容の行は1件にまとめて件数を持たせる。
        # 「区分ごとの線幅…」のように区分数だけ繰り返す指摘があるため。
        key = (level, category, message, detail)
        existing = self._seen.get(key)
        if existing is not None:
            existing.count += 1
            return existing
        entry = Entry(self.layer_name, level, category, message, detail)
        self._seen[key] = entry
        self.entries.append(entry)
        if self._parent is not None:
            self._parent.entries.append(entry)
        return entry

    def info(self, category, message, detail=""):
        return self._add(Level.INFO, category, message, detail)

    def approx(self, category, message, detail=""):
        return self._add(Level.APPROX, category, message, detail)

    def warn(self, category, message, detail=""):
        return self._add(Level.WARN, category, message, detail)

    def error(self, category, message, detail=""):
        return self._add(Level.ERROR, category, message, detail)

    # -------------------------------------------------------------- #
    def worst_level(self):
        if not self.entries:
            return Level.INFO
        return max((e.level for e in self.entries), key=lambda lv: Level.ORDER[lv])

    def count(self, level):
        return sum(1 for e in self.entries if e.level == level)

    def issue_count(self):
        """INFO を除いた件数。"""
        return sum(1 for e in self.entries if e.level != Level.INFO)

    def summary(self):
        parts = []
        for lv in (Level.ERROR, Level.WARN, Level.APPROX):
            n = self.count(lv)
            if n:
                parts.append("{0}{1}".format(Level.LABEL[lv], n))
        return " / ".join(parts) if parts else "—"


class ConversionReport(object):
    """全レイヤをまたぐレポート。"""

    def __init__(self):
        self.entries = []
        self.layers = []
        self.patches = set()

    def patch_lines(self):
        """後方互換のための空リスト（パッチ表示は廃止）。"""
        return []

    def layer(self, layer_name):
        rep = LayerReport(layer_name, parent=self)
        self.layers.append(rep)
        return rep

    def count(self, level):
        return sum(1 for e in self.entries if e.level == level)

    # -------------------------------------------------------------- #
    def to_text(self):
        """プレーンテキストのレポート。"""
        lines = []
        lines.append("fgstyle Maker 変換レポート")
        lines.append("生成日時: {0}".format(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        lines.append("")
        lines.append("集計: エラー {0} / 警告 {1} / 近似 {2} / 情報 {3}".format(
            self.count(Level.ERROR), self.count(Level.WARN),
            self.count(Level.APPROX), self.count(Level.INFO)))
        lines.append("")
        lines.append("区分の意味:")
        for lv in (Level.ERROR, Level.WARN, Level.APPROX, Level.INFO):
            lines.append("  {0} … {1}".format(Level.LABEL[lv], Level.ACTION[lv]))
        lines.append("=" * 68)

        for rep in self.layers:
            lines.append("")
            lines.append("■ {0}".format(rep.layer_name))
            if not rep.entries:
                lines.append("    （問題なし）")
                continue
            for e in sorted(rep.entries,
                            key=lambda x: -Level.ORDER[x.level]):
                lines.append("    [{0}] {1}: {2}".format(
                    Level.LABEL[e.level], e.category, e.text))
                if e.detail:
                    for dl in str(e.detail).splitlines():
                        lines.append("            {0}".format(dl))
        return "\n".join(lines)

    def to_markdown(self):
        lines = []
        lines.append("# fgstyle Maker 変換レポート")
        lines.append("")
        lines.append("生成日時: {0}".format(
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        lines.append("")
        lines.append("| 区分 | 件数 | 必要な対応 |")
        lines.append("| --- | --- | --- |")
        for lv in (Level.ERROR, Level.WARN, Level.APPROX, Level.INFO):
            lines.append("| {0} | {1} | {2} |".format(
                Level.LABEL[lv], self.count(lv), Level.ACTION[lv]))
        lines.append("")
        for rep in self.layers:
            lines.append("## {0}".format(rep.layer_name))
            lines.append("")
            if not rep.entries:
                lines.append("問題なし。")
                lines.append("")
                continue
            lines.append("| 区分 | 分類 | 内容 |")
            lines.append("| --- | --- | --- |")
            for e in sorted(rep.entries, key=lambda x: -Level.ORDER[x.level]):
                msg = e.text.replace("|", "\\|")
                if e.detail:
                    msg += "<br>" + str(e.detail).replace("|", "\\|").replace("\n", "<br>")
                lines.append("| {0} | {1} | {2} |".format(
                    Level.LABEL[e.level], e.category, msg))
            lines.append("")
        return "\n".join(lines)

    def to_html(self):
        """UIのプレビュー用（色分け付き）。"""
        color = {
            Level.ERROR: "#b71c1c",
            Level.WARN: "#ef6c00",
            Level.APPROX: "#1d6fa4",
            Level.INFO: "#555555",
        }
        out = ["<html><body style='font-family:sans-serif;font-size:12px;'>"]
        out.append("<p><b>集計</b>: エラー {0} / 警告 {1} / 近似 {2} / 情報 {3}</p>".format(
            self.count(Level.ERROR), self.count(Level.WARN),
            self.count(Level.APPROX), self.count(Level.INFO)))
        out.append("<p style='color:#555;font-size:11px;'>" + " ／ ".join(
            "<b>{0}</b>={1}".format(Level.LABEL[lv], Level.ACTION[lv])
            for lv in (Level.ERROR, Level.WARN, Level.APPROX, Level.INFO)) + "</p>")
        for rep in self.layers:
            out.append("<h3 style='margin:8px 0 2px 0;'>{0}</h3>".format(
                _esc(rep.layer_name)))
            if not rep.entries:
                out.append("<div style='color:#888;'>問題なし</div>")
                continue
            out.append("<ul style='margin:2px 0 2px 16px;padding:0;'>")
            for e in sorted(rep.entries, key=lambda x: -Level.ORDER[x.level]):
                out.append(
                    "<li><span style='color:{0};font-weight:bold;'>[{1}]</span> "
                    "<i>{2}</i> — {3}{4}</li>".format(
                        color[e.level], Level.LABEL[e.level], _esc(e.category),
                        _esc(e.text),
                        "<br><span style='color:#777;'>{0}</span>".format(
                            _esc(str(e.detail))) if e.detail else ""))
            out.append("</ul>")
        out.append("</body></html>")
        return "".join(out)


def _esc(text):
    return (str(text).replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))
