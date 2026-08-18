# -*- coding: utf-8 -*-
"""QGIS式の限定パーサ。

MapLibre の match / step 式に落とせる形（単一フィールドに対する
等値・IN・範囲比較）だけを解釈する。それ以外は None を返し、
呼び出し側が警告する。
"""

import re

# フィールド参照: "樹種" / 樹種 / "fld"
_FIELD = r'(?:"(?P<q_{0}>[^"]+)"|(?P<b_{0}>[A-Za-z_々぀-ヿ㐀-鿿][\w々぀-ヿ㐀-鿿]*))'
_NUM = r'(?P<n_{0}>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
_STR = r"'(?P<s_{0}>(?:[^']|'')*)'"


def _f(pattern, tag):
    return pattern.format(tag)


def _field_of(m, tag):
    return m.group("q_" + tag) or m.group("b_" + tag)


def _unquote(text):
    return text.replace("''", "'") if text is not None else None


class ParsedCondition(object):
    """パース結果。

    kind:
        'value'   … 文字列（等値）条件。values に候補が入る
        'range'   … 数値範囲条件。num_min / num_max
        'else'    … ELSEルール（既定色）
    """

    __slots__ = ("kind", "field", "values", "num_min", "num_max", "numeric_literal")

    def __init__(self, kind, field=None, values=None, num_min=None, num_max=None,
                 numeric_literal=False):
        self.kind = kind
        self.field = field
        self.values = values or []
        self.num_min = num_min
        self.num_max = num_max
        # 'value' 種別で、比較対象が数値リテラルだったか。
        # 数値属性に対して MapLibre の match 式は型厳密比較になるため、
        # 呼び出し側で警告／別表現への切り替えが必要になる。
        self.numeric_literal = bool(numeric_literal)

    def __repr__(self):
        return "<ParsedCondition {0} field={1} values={2} [{3},{4}] num={5}>".format(
            self.kind, self.field, self.values, self.num_min, self.num_max,
            self.numeric_literal)


# --------------------------------------------------------------------- #
_RE_ELSE = re.compile(r'^\s*(?:else|ELSE|TRUE|true|1)\s*$')

# 等値演算子。QGISは `=` のほか `IS`（NULL安全な等値）も書ける。
# ベクトルタイルのスタイル式は `"樹種" IS 'スギ'` の形が既定なので必須。
_EQ_OP = r'\s*(?:==?|\s+IS\s+)\s*'

_RE_EQ_STR = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + _EQ_OP + _f(_STR, 'a') + r'\s*$',
    re.IGNORECASE)

_RE_EQ_NUM = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + _EQ_OP + _f(_NUM, 'a') + r'\s*$',
    re.IGNORECASE)

_RE_IS_NULL = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + r'\s+IS\s+NULL\s*$', re.IGNORECASE)

_RE_IN = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + r'\s+IN\s*\((?P<list>.+)\)\s*$', re.IGNORECASE)

# "fld" >= 10 AND "fld" < 20
_RE_RANGE = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + r'\s*(?P<op1>>=|>)\s*' + _f(_NUM, 'a') +
    r'\s+AND\s+' + _f(_FIELD, 'b') + r'\s*(?P<op2><=|<)\s*' + _f(_NUM, 'b') +
    r'\s*$', re.IGNORECASE)

_RE_GE = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + r'\s*(?P<op>>=|>)\s*' + _f(_NUM, 'a') + r'\s*$')

_RE_LE = re.compile(
    r'^\s*' + _f(_FIELD, 'a') + r'\s*(?P<op><=|<)\s*' + _f(_NUM, 'a') + r'\s*$')

_RE_LIST_ITEM = re.compile(r"'((?:[^']|'')*)'|(-?\d+(?:\.\d+)?)")


def parse_condition(expression):
    """QGIS式を ParsedCondition に変換する。解釈できなければ None。"""
    if expression is None:
        return None
    expr = str(expression).strip()
    if expr == "":
        return ParsedCondition("else")
    if _RE_ELSE.match(expr):
        return ParsedCondition("else")

    # `IS NULL` は等値より先に見る（`IS` を等値演算子として食わせない）
    m = _RE_IS_NULL.match(expr)
    if m:
        return ParsedCondition("value", _field_of(m, 'a'), values=[""])

    m = _RE_EQ_STR.match(expr)
    if m:
        return ParsedCondition("value", _field_of(m, 'a'),
                               values=[_unquote(m.group("s_a"))])

    m = _RE_EQ_NUM.match(expr)
    if m:
        return ParsedCondition("value", _field_of(m, 'a'),
                               values=[_normalize_number_text(m.group("n_a"))],
                               numeric_literal=True)

    m = _RE_IN.match(expr)
    if m:
        items = []
        all_numeric = True
        for sm in _RE_LIST_ITEM.finditer(m.group("list")):
            if sm.group(1) is not None:
                items.append(_unquote(sm.group(1)))
                all_numeric = False
            else:
                items.append(_normalize_number_text(sm.group(2)))
        if items:
            return ParsedCondition("value", _field_of(m, 'a'), values=items,
                                   numeric_literal=all_numeric)
        return None

    m = _RE_RANGE.match(expr)
    if m:
        f1, f2 = _field_of(m, 'a'), _field_of(m, 'b')
        if f1 != f2:
            return None
        lo = float(m.group("n_a"))
        hi = float(m.group("n_b"))
        # 「>」の場合も step 式では下限扱いにするしかない（境界1点の差は無視）
        return ParsedCondition("range", f1, num_min=lo, num_max=hi)

    m = _RE_GE.match(expr)
    if m:
        return ParsedCondition("range", _field_of(m, 'a'),
                               num_min=float(m.group("n_a")))

    m = _RE_LE.match(expr)
    if m:
        return ParsedCondition("range", _field_of(m, 'a'),
                               num_max=float(m.group("n_a")))

    return None


def _normalize_number_text(text):
    """'10' → '10'、'10.0' → '10' に寄せる（属性値の文字列一致用）。"""
    try:
        v = float(text)
        if v == int(v):
            return str(int(v))
        return str(v)
    except (TypeError, ValueError):
        return str(text)


# --------------------------------------------------------------------- #
_RE_PLAIN_FIELD = re.compile(
    r'^\s*(?:"([^"]+)"|([A-Za-z_々぀-ヿ㐀-鿿]'
    r'[\w々぀-ヿ㐀-鿿]*))\s*$')


def plain_field_name(expression):
    """式が単なるフィールド参照ならフィールド名を、そうでなければ None。

    MapLibre の ["get", field] はフィールド名しか受け付けないため、
    分類フィールドが式になっている場合はここで弾く。
    """
    if expression is None:
        return None
    m = _RE_PLAIN_FIELD.match(str(expression))
    if not m:
        return None
    return m.group(1) or m.group(2)
