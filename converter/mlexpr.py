# -*- coding: utf-8 -*-
"""QGIS式 → MapLibre GL JS 式 のトランスレータ。

互換性レポートが「最重要課題」に挙げている部分。
QGISのフィルタ式・データ定義プロパティ式を、MapLibre の式配列へ変換する。

対応するのは「1地物だけを見て評価できる」式に限る。
集計関数、ジオメトリ関数、レイヤ参照、変数（@…）は変換できない。

    >>> translate('"樹種" = \\'スギ\\'')
    ['==', ['get', '樹種'], 'スギ']
    >>> translate('"林齢" >= 10 AND "林齢" < 20')
    ['all', ['>=', ['get', '林齢'], 10], ['<', ['get', '林齢'], 20]]
"""

import re


class UnsupportedExpression(Exception):
    """MapLibre式へ変換できない構文・関数に出会った。"""

    def __init__(self, message, fragment=""):
        super(UnsupportedExpression, self).__init__(message)
        self.message = message
        self.fragment = fragment


# ===================================================================== #
# 字句解析
# ===================================================================== #
_KEYWORDS = {
    "and", "or", "not", "in", "is", "null", "like", "ilike", "between",
    "case", "when", "then", "else", "end", "true", "false",
}

_TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>--[^\n]*)
  | (?P<number>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?)
  | (?P<string>'(?:[^']|'')*')
  | (?P<field>"(?:[^"]|"")*")
  | (?P<variable>@[A-Za-z_][\w]*)
  | (?P<special>\$[A-Za-z_][\w]*)
  | (?P<ident>[A-Za-z_À-￿][\wÀ-￿]*)
  | (?P<op><>|!=|<=|>=|\|\||[-+*/%^=<>(),])
""", re.VERBOSE)


class Token(object):
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind, self.value, self.pos = kind, value, pos

    def __repr__(self):
        return "<{0} {1!r}>".format(self.kind, self.value)


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        m = _TOKEN_RE.match(text, i)
        if not m:
            raise UnsupportedExpression(
                "解釈できない文字があります", text[i:i + 12])
        i = m.end()
        kind = m.lastgroup
        raw = m.group()
        if kind in ("ws", "comment"):
            continue
        if kind == "ident" and raw.lower() in _KEYWORDS:
            tokens.append(Token("kw", raw.lower(), m.start()))
        else:
            tokens.append(Token(kind, raw, m.start()))
    tokens.append(Token("eof", "", n))
    return tokens


def _unquote_string(raw):
    return raw[1:-1].replace("''", "'")


def _unquote_field(raw):
    return raw[1:-1].replace('""', '"')


# ===================================================================== #
# 関数の対応表
# ===================================================================== #
def _fn_concat(args):
    return ["concat"] + [["to-string", a] for a in args]


def _fn_substr(args):
    # QGIS の substr は1始まり。MapLibre の slice は0始まり。
    if len(args) == 2:
        start = args[1]
        return ["slice", ["to-string", args[0]], _minus_one(start)]
    if len(args) == 3:
        start, length = args[1], args[2]
        begin = _minus_one(start)
        return ["slice", ["to-string", args[0]], begin, ["+", begin, length]]
    raise UnsupportedExpression("substr の引数の数が不正です")


def _minus_one(value):
    if isinstance(value, (int, float)):
        return value - 1
    return ["-", value, 1]


def _fn_round(args):
    if len(args) == 1:
        return ["round", args[0]]
    if len(args) == 2 and isinstance(args[1], (int, float)):
        factor = 10 ** int(args[1])
        if factor == 1:
            return ["round", args[0]]
        return ["/", ["round", ["*", args[0], factor]], factor]
    raise UnsupportedExpression("round の桁数は定数のみ対応です")


def _fn_if(args):
    if len(args) != 3:
        raise UnsupportedExpression("if() は3引数のみ対応です")
    return ["case", args[0], args[1], args[2]]


def _fn_exp(args):
    return ["^", ["e"], args[0]]


def _simple(name, min_args=1, max_args=None):
    def build(args):
        if len(args) < min_args or (max_args is not None and len(args) > max_args):
            raise UnsupportedExpression("{0} の引数の数が不正です".format(name))
        return [name] + list(args)
    return build


_FUNCTIONS = {
    # 文字列
    "concat": _fn_concat,
    "upper": _simple("upcase", 1, 1),
    "lower": _simple("downcase", 1, 1),
    "length": _simple("length", 1, 1),
    "substr": _fn_substr,
    # 型変換
    "to_string": _simple("to-string", 1, 1),
    "tostring": _simple("to-string", 1, 1),
    "to_real": _simple("to-number", 1, 1),
    "to_double": _simple("to-number", 1, 1),
    "toreal": _simple("to-number", 1, 1),
    "to_int": lambda a: ["round", ["to-number", a[0]]],
    "toint": lambda a: ["round", ["to-number", a[0]]],
    # 数学
    "abs": _simple("abs", 1, 1),
    "round": _fn_round,
    "floor": _simple("floor", 1, 1),
    "ceil": _simple("ceil", 1, 1),
    "sqrt": _simple("sqrt", 1, 1),
    "ln": _simple("ln", 1, 1),
    "log10": _simple("log10", 1, 1),
    "exp": _fn_exp,
    "min": _simple("min", 1),
    "max": _simple("max", 1),
    # 制御
    "coalesce": _simple("coalesce", 1),
    "if": _fn_if,
}

# 明示的に「変換できない」と分かっている関数（親切なメッセージを出すため）
_KNOWN_UNSUPPORTED = {
    "geometry": "ジオメトリ関数", "buffer": "ジオメトリ関数",
    "centroid": "ジオメトリ関数", "area": "ジオメトリ関数",
    "length3d": "ジオメトリ関数", "x": "ジオメトリ関数", "y": "ジオメトリ関数",
    "aggregate": "集計関数", "sum": "集計関数", "count": "集計関数",
    "mean": "集計関数", "minimum": "集計関数", "maximum": "集計関数",
    "attribute": "属性動的参照", "get_feature": "他レイヤ参照",
    "represent_value": "他レイヤ参照", "relation_aggregate": "リレーション集計",
    "format_number": "書式関数", "format_date": "書式関数",
    "now": "日時関数", "age": "日時関数", "to_date": "日時関数",
    "regexp_match": "正規表現", "regexp_replace": "正規表現",
    "regexp_substr": "正規表現", "map_get": "マップ型",
    "array_length": "配列関数", "array_contains": "配列関数",
    "ramp_color": "カラーランプ", "color_rgb": "色関数",
    "scale_linear": "スケール関数", "scale_exp": "スケール関数",
    "rand": "乱数", "randf": "乱数",
}


# ===================================================================== #
# 構文解析（優先順位上昇法）
# ===================================================================== #
class Parser(object):

    def __init__(self, tokens, text=""):
        self.tokens = tokens
        self.i = 0
        self.text = text

    # -- トークン操作 ---------------------------------------------- #
    def peek(self):
        return self.tokens[self.i]

    def next(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def accept(self, kind, value=None):
        tok = self.peek()
        if tok.kind == kind and (value is None or tok.value == value):
            self.i += 1
            return tok
        return None

    def expect(self, kind, value=None):
        tok = self.accept(kind, value)
        if tok is None:
            raise UnsupportedExpression(
                "『{0}』が来るべき位置に {1!r} があります".format(
                    value or kind, self.peek().value),
                self.text)
        return tok

    # -- エントリ --------------------------------------------------- #
    def parse(self):
        node = self.parse_or()
        if self.peek().kind != "eof":
            raise UnsupportedExpression(
                "式の末尾に余分な要素 {0!r} があります".format(self.peek().value),
                self.text)
        return node

    # -- 優先順位ごと ----------------------------------------------- #
    def parse_or(self):
        parts = [self.parse_and()]
        while self.accept("kw", "or"):
            parts.append(self.parse_and())
        return parts[0] if len(parts) == 1 else ["any"] + parts

    def parse_and(self):
        parts = [self.parse_not()]
        while self.accept("kw", "and"):
            parts.append(self.parse_not())
        return parts[0] if len(parts) == 1 else ["all"] + parts

    def parse_not(self):
        if self.accept("kw", "not"):
            return ["!", self.parse_not()]
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_concat()

        negate = bool(self.accept("kw", "not"))   # "x NOT IN (...)" / "NOT LIKE"

        tok = self.peek()
        if tok.kind == "kw" and tok.value == "is":
            self.next()
            inner_not = bool(self.accept("kw", "not"))
            self.expect("kw", "null")
            node = ["==", left, None]
            if inner_not != negate:
                node = ["!", node]
            return node

        if tok.kind == "kw" and tok.value == "in":
            self.next()
            node = self._parse_in(left)
            return ["!", node] if negate else node

        if tok.kind == "kw" and tok.value == "between":
            self.next()
            low = self.parse_concat()
            self.expect("kw", "and")
            high = self.parse_concat()
            node = ["all", [">=", left, low], ["<=", left, high]]
            return ["!", node] if negate else node

        if tok.kind == "kw" and tok.value in ("like", "ilike"):
            self.next()
            pattern = self.parse_concat()
            node = self._parse_like(left, pattern, tok.value == "ilike")
            return ["!", node] if negate else node

        if negate:
            raise UnsupportedExpression("NOT の使い方を解釈できません", self.text)

        if tok.kind == "op" and tok.value in ("=", "<>", "!=", "<", "<=", ">", ">="):
            self.next()
            right = self.parse_concat()
            op = {"=": "==", "<>": "!=", "!=": "!="}.get(tok.value, tok.value)
            return [op, left, right]

        return left

    def _parse_in(self, left):
        self.expect("op", "(")
        items = [self.parse_concat()]
        while self.accept("op", ","):
            items.append(self.parse_concat())
        self.expect("op", ")")
        if not all(isinstance(v, (str, int, float, bool)) for v in items):
            raise UnsupportedExpression(
                "IN の候補はリテラルのみ対応です", self.text)
        return ["in", left, ["literal", list(items)]]

    def _parse_like(self, left, pattern, case_insensitive):
        if not isinstance(pattern, str):
            raise UnsupportedExpression(
                "LIKE のパターンは文字列リテラルのみ対応です", self.text)
        if "%" in pattern or "_" in pattern:
            raise UnsupportedExpression(
                "ワイルドカードを含む LIKE は MapLibre に相当機能がありません",
                pattern)
        # ワイルドカード無し = 完全一致
        if case_insensitive:
            return ["==", ["downcase", ["to-string", left]], pattern.lower()]
        return ["==", left, pattern]

    def parse_concat(self):
        left = self.parse_additive()
        parts = None
        while self.accept("op", "||"):
            if parts is None:
                parts = [left]
            parts.append(self.parse_additive())
        if parts is None:
            return left
        return ["concat"] + [["to-string", p] for p in parts]

    def parse_additive(self):
        left = self.parse_multiplicative()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("+", "-"):
                self.next()
                left = [tok.value, left, self.parse_multiplicative()]
            else:
                return left

    def parse_multiplicative(self):
        left = self.parse_power()
        while True:
            tok = self.peek()
            if tok.kind == "op" and tok.value in ("*", "/", "%"):
                self.next()
                left = [tok.value, left, self.parse_power()]
            else:
                return left

    def parse_power(self):
        left = self.parse_unary()
        if self.accept("op", "^"):
            return ["^", left, self.parse_power()]   # 右結合
        return left

    def parse_unary(self):
        if self.accept("op", "-"):
            operand = self.parse_unary()
            if isinstance(operand, (int, float)):
                return -operand
            return ["-", 0, operand]
        self.accept("op", "+")
        return self.parse_primary()

    # -- 終端 -------------------------------------------------------- #
    def parse_primary(self):
        tok = self.next()

        if tok.kind == "number":
            value = float(tok.value)
            return int(value) if value == int(value) and "." not in tok.value \
                and "e" not in tok.value.lower() else value

        if tok.kind == "string":
            return _unquote_string(tok.value)

        if tok.kind == "field":
            return ["get", _unquote_field(tok.value)]

        if tok.kind == "variable":
            raise UnsupportedExpression(
                "変数 {0} は変換できません".format(tok.value), tok.value)

        if tok.kind == "special":
            if tok.value.lower() == "$id":
                return ["id"]
            raise UnsupportedExpression(
                "{0} は変換できません".format(tok.value), tok.value)

        if tok.kind == "kw":
            if tok.value == "true":
                return True
            if tok.value == "false":
                return False
            if tok.value == "null":
                return None
            if tok.value == "case":
                return self.parse_case()
            raise UnsupportedExpression(
                "予期しないキーワード {0!r}".format(tok.value), self.text)

        if tok.kind == "op" and tok.value == "(":
            node = self.parse_or()
            self.expect("op", ")")
            return node

        if tok.kind == "ident":
            if self.peek().kind == "op" and self.peek().value == "(":
                return self.parse_function(tok.value)
            # 引用符なしのフィールド参照
            return ["get", tok.value]

        raise UnsupportedExpression(
            "解釈できない要素 {0!r}".format(tok.value), self.text)

    def parse_function(self, name):
        self.expect("op", "(")
        args = []
        if not (self.peek().kind == "op" and self.peek().value == ")"):
            args.append(self.parse_or())
            while self.accept("op", ","):
                args.append(self.parse_or())
        self.expect("op", ")")

        key = name.lower()
        if key in _FUNCTIONS:
            return _FUNCTIONS[key](args)
        if key in _KNOWN_UNSUPPORTED:
            raise UnsupportedExpression(
                "{0} {1}() は MapLibre 式へ変換できません".format(
                    _KNOWN_UNSUPPORTED[key], name), name)
        raise UnsupportedExpression(
            "未対応の関数 {0}() です".format(name), name)

    def parse_case(self):
        branches = []
        while self.accept("kw", "when"):
            cond = self.parse_or()
            self.expect("kw", "then")
            branches.append((cond, self.parse_or()))
        default = None
        if self.accept("kw", "else"):
            default = self.parse_or()
        self.expect("kw", "end")
        if not branches:
            raise UnsupportedExpression("CASE に WHEN がありません", self.text)
        out = ["case"]
        for cond, value in branches:
            out.append(cond)
            out.append(value)
        out.append(default)
        return out


# ===================================================================== #
# 公開API
# ===================================================================== #
def translate(expression):
    """QGIS式 → MapLibre式。変換できなければ UnsupportedExpression。"""
    if expression is None:
        raise UnsupportedExpression("式が空です")
    text = str(expression).strip()
    if text == "":
        raise UnsupportedExpression("式が空です")
    return Parser(tokenize(text), text).parse()


def try_translate(expression):
    """変換できれば MapLibre式、できなければ (None, 理由) を返す。

    戻り値: (expr, error_message)
    """
    try:
        return translate(expression), None
    except UnsupportedExpression as exc:
        return None, exc.message
    except Exception as exc:                      # 想定外の構文崩れ
        return None, "式を解析できませんでした（{0}）".format(exc)


def as_boolean(expr):
    """式を MapLibre の真偽値として使える形にする。

    比較・論理演算はそのまま。フィールド参照だけの式は「非nullかつ真」に。
    """
    if isinstance(expr, bool):
        return expr
    if isinstance(expr, list) and expr and expr[0] in (
            "==", "!=", "<", "<=", ">", ">=", "all", "any", "!", "in", "has"):
        return expr
    return ["to-boolean", expr]


def collect_fields(expr, out=None):
    """式が参照している属性名を集める（スタブレイヤの列作成などに使う）。"""
    if out is None:
        out = []
    if isinstance(expr, list):
        if len(expr) == 2 and expr[0] == "get" and isinstance(expr[1], str):
            if expr[1] not in out:
                out.append(expr[1])
            return out
        for item in expr:
            collect_fields(item, out)
    return out
