# -*- coding: utf-8 -*-
"""QgsSymbol から MapLibre に落とせる属性（色・幅・半径・不透明度）を抽出する。

戻り値はすべて `SymbolProps` に統一し、レンダラ側は幾何種別ごとに
必要なキーだけを拾う。
"""

from .mlexpr import try_translate
from .units import (color_to_hex, color_alpha, blend_colors, rgba_color,
                    to_pixels, to_pixels_expression, round_px, clamp01,
                    is_expression)


class SymbolProps(object):
    """1シンボルから取り出した描画属性。値が None なら「取得できなかった」。"""

    __slots__ = ("color", "opacity", "width", "radius",
                 "stroke_color", "stroke_width", "stroke_opacity", "dasharray",
                 "dash_base_width", "hairline", "stroke_hairline",
                 "casing_color", "casing_width")

    def __init__(self):
        self.color = None            # '#rrggbb'（塗り／線／円の主色）
        self.opacity = None          # 0.0-1.0
        self.width = None            # px（線幅）
        self.radius = None           # px（円半径）
        self.stroke_color = None     # '#rrggbb'
        self.stroke_width = None     # px
        self.stroke_opacity = None   # 0.0-1.0
        self.dasharray = None        # 破線パターン（線幅の倍数のリスト）
        # dasharray を「線幅の倍数」に直すときに割った線幅(px)。
        # QGISのカスタムダッシュは絶対長(mm/px)なので、最終線幅が
        # 変わったら倍数を再計算しないと絶対長がずれる。
        # Qt既定パターン（破線・点線など）は元から線幅の倍数なので None。
        self.dash_base_width = None
        # QGISの「非常に細い線」（ヘアライン）。幅0だが**描画される**。
        # 幅0＝線なし（NoPen）と区別するために持つ。
        self.hairline = False          # 線本体
        self.stroke_hairline = False   # 縁取り・外周線
        # 縁取り（casing）。道路のように「太い線の上に細い線を重ねる」表現で、
        # 下に敷く太い線の色と総幅（px）。幅 None／0 なら縁取り無し。
        self.casing_color = None
        self.casing_width = None

    def __repr__(self):
        return "<SymbolProps {0}>".format(
            {k: getattr(self, k) for k in self.__slots__})


# --------------------------------------------------------------------- #
def _class_name(obj):
    return type(obj).__name__ if obj is not None else ""


def _first_layer(symbol):
    try:
        if symbol.symbolLayerCount() > 0:
            return symbol.symbolLayer(0)
    except Exception:
        pass
    return None


def _check_layer_count(symbol, report, what):
    try:
        n = symbol.symbolLayerCount()
    except Exception:
        return
    if n > 1:
        report.approx(
            "シンボル",
            "{0}が{1}枚のシンボルレイヤで構成されているため、先頭の1枚のみ変換しました"
            .format(what, n),
            "重ね描き（キャップ表現・二重線など）はMapLibre側で再現されません。")


def _symbol_opacity(symbol):
    try:
        return float(symbol.opacity())
    except Exception:
        return 1.0


#: QGISのプロパティ定義名 → 内部での役割
#  QGIS 3.30 で enum の置き場所が変わったため、propertyDefinitions() の
#  name() 文字列で判定する（バージョン差に強い）。
def _classify_property(name):
    key = (name or "").lower().replace("_", "")
    if key in ("fillcolor", "color", "color1"):
        return "color"
    if key in ("strokecolor", "outlinecolor", "bordercolor", "color2"):
        return "stroke_color"
    if key in ("strokewidth", "outlinewidth", "borderwidth"):
        return "stroke_width"
    if key in ("width", "linewidth"):
        return "width"
    if key == "size":
        return "size"
    if key in ("alpha", "opacity"):
        return "opacity"
    if key in ("angle", "rotation", "linheight"):
        return "angle"
    return None


def _property_expression(prop):
    """QgsProperty → QGIS式文字列。取り出せなければ None。"""
    try:
        if not prop.isActive():
            return None
    except Exception:
        pass
    for getter in ("asExpression", "expressionString"):
        try:
            text = getattr(prop, getter)()
            if text:
                return str(text)
        except Exception:
            continue
    try:
        field = prop.field()
        if field:
            return '"{0}"'.format(field)
    except Exception:
        pass
    return None


def data_defined_expressions(symbol_layer, opts, report, what):
    """データ定義プロパティ → {役割: MapLibre式} の辞書。

    `allow_expressions` が無効なときは変換せず警告だけ出す（従来動作）。
    """
    out = {}
    try:
        coll = symbol_layer.dataDefinedProperties()
        if coll is None or not coll.hasActiveProperties():
            return out
        keys = list(coll.propertyKeys())
        definitions = type(symbol_layer).propertyDefinitions()
    except Exception:
        return out

    if not getattr(opts, "allow_expressions", False):
        report.warn(
            "データ定義",
            "{0}にデータ定義（式）による上書きがありますが、"
            "式の出力が無効なため変換できません".format(what),
            "『MapLibre式を使う』を有効にすると変換を試みます。")
        return out

    for key in keys:
        try:
            prop = coll.property(key)
        except Exception:
            continue
        text = _property_expression(prop)
        if not text:
            continue

        definition = definitions.get(key) if hasattr(definitions, "get") else None
        name = ""
        try:
            name = definition.name() if definition is not None else ""
        except Exception:
            name = ""
        role = _classify_property(name)

        if role is None:
            report.warn("データ定義",
                        "{0}のデータ定義『{1}』は対応キーがないため無視しました"
                        .format(what, name or key))
            continue
        if role == "angle":
            report.warn("データ定義",
                        "{0}の回転角のデータ定義は変換できません".format(what))
            continue

        expr, err = try_translate(text)
        if expr is None:
            report.warn(
                "データ定義",
                "{0}の『{1}』の式を変換できませんでした".format(what, name or key),
                "{0}\n式: {1}".format(err, text))
            continue

        out[role] = expr
        report.info(
            "データ定義",
            "{0}の『{1}』をMapLibre式へ変換しました".format(what, name or key),
            "式: {0}".format(text))
        report.need_patch("expr-safe")

    if out:
        report.info(
            "データ定義",
            "色のデータ定義は、式の結果が '#rrggbb' 形式の文字列である必要があります",
            "QGISの '255,0,0' 形式を返す式はMapLibreで解釈されません。")
    return out


def _has_data_defined(symbol_layer, report, what):
    """後方互換のための薄いラッパー（警告のみ）。"""
    try:
        props = symbol_layer.dataDefinedProperties()
        if props is not None and props.hasActiveProperties():
            return True
    except Exception:
        pass
    return False



def _scale(value, factor):
    """スカラーでも式でも掛け算する。"""
    if value is None:
        return None
    if is_expression(value):
        return ["*", value, factor]
    return float(value) * factor


def _allow(opts):
    return bool(getattr(opts, "allow_expressions", False))


def _record_unit(report, unit, raw, px):
    """どの単位の値がどのピクセル値になったかを集計する。

    「QMLはピクセル指定なのに細く見える」といった追跡ができるように、
    レイヤ単位で1件のサマリとしてレポートへ出す（各カテゴリごとに出すと
    数百件になるため）。
    """
    if report is None or px is None or is_expression(px):
        return
    try:
        raw = float(raw)
    except (TypeError, ValueError):
        return
    usage = getattr(report, "_unit_usage", None)
    if usage is None:
        usage = {}
        setattr(report, "_unit_usage", usage)
    usage[(str(unit), round(raw, 4))] = round(float(px), 3)


def _call(obj, name):
    """obj.name() を呼ぶ。メソッドが無い／例外なら None。

    QGIS の API はバージョンで getter の有無が変わるため、
    「あるかどうか」を hasattr ではなく実際の呼び出しで確かめる。
    """
    if obj is None:
        return None
    method = getattr(obj, name, None)
    if method is None:
        return None
    try:
        return method()
    except Exception:
        return None


def is_hairline(width, pen_style_getter):
    """QGISの「非常に細い線」か。

    QGISは幅0を **ヘアライン**（画面上は1デバイスピクセル）として描く。
    線を消したいときは幅ではなく線種を「線なし」(NoPen) にする。
    したがって

        幅が0  かつ  線種が NoPen 以外   →  ヘアライン（描画される）
        線種が NoPen                     →  線なし（描画されない）

    MapLibre には「ヘアライン」の概念が無く `line-width: 0` は
    文字どおり何も描かないので、最小可視幅へ引き上げる必要がある。
    """
    try:
        if width is None or float(width) > 0:
            return False
    except (TypeError, ValueError):
        return False
    try:
        from qgis.PyQt.QtCore import Qt as _Qt
    except ImportError:
        return False
    try:
        style = pen_style_getter()
    except Exception:
        return False
    return style != _Qt.NoPen


def line_width_and_unit(symbol, symbol_layer=None):
    """線幅と単位を (値, 単位) で返す。

    **`QgsLineSymbol` には `widthUnit()` ゲッターが無い**（`setWidthUnit()`
    しか無い）バージョンがあるため、シンボルレイヤ側の
    `QgsLineSymbolLayer.width()` / `widthUnit()` を優先して読む。
    ここを symbol 側だけに頼ると、QGIS 上では単位が取れず

      * 線幅が px へ換算できない（既定値 2.0 のまま出る）
      * カスタムダッシュを線幅で割れず「換算できませんでした」警告

    という形で静かに失敗する。
    """
    width = _call(symbol_layer, "width")
    unit = _call(symbol_layer, "widthUnit")
    if unit is None:
        unit = _call(symbol_layer, "outputUnit")
    if width is None:
        width = _call(symbol, "width")
    if unit is None:
        unit = _call(symbol, "widthUnit")
    if width is None:
        # 最後の手段: 線シンボルレイヤの stroke 系ゲッター
        width = _call(symbol_layer, "strokeWidth")
        if unit is None:
            unit = _call(symbol_layer, "strokeWidthUnit")
    return width, unit


def _px(value, unit, opts, report, what):
    """寸法 → px。allow_expressions が有効ならマップ単位も式で表せる。"""
    from .units import encode_render_unit
    code = encode_render_unit(unit)
    if _allow(opts):
        px = to_pixels_expression(value, unit, opts, report, what)
    else:
        px = to_pixels(value, unit, opts, report, what)
    _record_unit(report, code, value, px)
    return px


# --------------------------------------------------------------------- #
# 破線パターン
# --------------------------------------------------------------------- #
#: Qt の QPen 既定パターン（線幅の倍数）。MapLibre の line-dasharray と
#  同じ「線幅の倍数」表現なので、そのまま渡せる。
_QT_PEN_DASH = {
    "DashLine": [4, 2],
    "DotLine": [1, 2],
    "DashDotLine": [4, 2, 1, 2],
    "DashDotDotLine": [4, 2, 1, 2, 1, 2],
}


def _pen_style_name(symbol_layer):
    """penStyle() を Qt の名前文字列へ（PyQt の enum 差を吸収）。"""
    try:
        from qgis.PyQt.QtCore import Qt as _Qt
    except ImportError:
        return ""
    try:
        style = symbol_layer.penStyle()
    except Exception:
        return ""
    for name in ("SolidLine", "DashLine", "DotLine", "DashDotLine",
                 "DashDotDotLine", "NoPen", "CustomDashLine"):
        if getattr(_Qt, name, None) == style:
            return name
    return ""


def dash_pattern(symbol_layer, symbol, opts, report, what):
    """QGISの線種 → (line-dasharray, 基準線幅px)。

    戻り値のパターンは MapLibre の line-dasharray と同じ「線幅の倍数」。
    実線なら `([], None)`。

    第2要素は、絶対長（mm/px）で書かれたカスタムダッシュを倍数へ直す
    ときに割った線幅。あとで線幅が変わった場合（最小線幅への引き上げ等）
    に絶対長を保つよう倍数を再計算するために返す。
    Qt の既定パターン（破線・点線・鎖線）は元から線幅の倍数なので None。
    """
    if symbol_layer is None:
        return [], None

    # --- カスタムダッシュパターン --------------------------------- #
    try:
        if symbol_layer.useCustomDashPattern():
            vector = list(_call(symbol_layer, "customDashVector") or [])
            unit = _call(symbol_layer, "customDashPatternUnit")
            raw_w, w_unit = line_width_and_unit(symbol, symbol_layer)
            width_px = to_pixels(raw_w, w_unit, opts, None, "")
            if len(vector) >= 2:
                lengths = [to_pixels(v, unit, opts, None, "") for v in vector]
                if all(v is not None for v in lengths) and width_px:
                    pattern = [round(max(v / width_px, 0.05), 3) for v in lengths]
                    report.info(
                        "線種",
                        "{0}のカスタムダッシュを line-dasharray {1} へ変換しました"
                        .format(what, pattern),
                        "MapLibre の line-dasharray は線幅の倍数なので、"
                        "線幅 {0:.2f}px で割って無次元化しています"
                        "（実寸は 線分 {1:.2f}px / 隙間 {2:.2f}px）。".format(
                            width_px, lengths[0], lengths[1]))
                    _warn_dash_offset(symbol_layer, report, what)
                    return pattern, width_px
            # 何が取れなかったのかを出す（原因の切り分けに必要）
            report.warn(
                "線種",
                "{0}のカスタムダッシュを換算できませんでした".format(what),
                "パターン={0} / パターン単位={1} / 線幅={2} / 線幅単位={3} "
                "→ 線幅px={4}。線幅が取れないと『線幅の倍数』へ直せません。"
                .format(vector, unit, raw_w, w_unit, width_px))
            return [], None
    except Exception:
        pass

    # --- 定型の線種 ------------------------------------------------ #
    name = _pen_style_name(symbol_layer)
    if name in _QT_PEN_DASH:
        report.info(
            "線種",
            "{0}の線種『{1}』を line-dasharray {2} へ変換しました".format(
                what, name, _QT_PEN_DASH[name]),
            "Qt の既定パターンと同じ比率です（線幅の倍数）。")
        _warn_dash_offset(symbol_layer, report, what)
        return list(_QT_PEN_DASH[name]), None
    return [], None


def _warn_dash_offset(symbol_layer, report, what):
    try:
        offset = float(symbol_layer.dashPatternOffset())
    except Exception:
        return
    if abs(offset) > 1e-9:
        report.warn(
            "線種",
            "{0}のダッシュ開始位置オフセットは変換できません".format(what),
            "MapLibre に line-dasharray の位相指定がありません。")


# --------------------------------------------------------------------- #
# マーカー（点）
# --------------------------------------------------------------------- #
_SIMPLE_MARKER_CIRCLE_SHAPES = ("Circle",)


def marker_props(symbol, opts, report, what="点シンボル"):
    """QgsMarkerSymbol → SymbolProps（radius / color / stroke_*）。"""
    p = SymbolProps()
    if symbol is None:
        return p

    _check_layer_count(symbol, report, what)
    base_opacity = _symbol_opacity(symbol)

    color = None
    try:
        color = symbol.color()
    except Exception:
        pass

    if _allow(opts):
        # 点は不透明度の対応キーが無いので、色に畳み込む（rgba()）。
        # MapLibre は rgba() をそのまま受け付ける。
        p.color = rgba_color(color, base_opacity)
        p.opacity = 1.0
        if p.color and p.color.startswith("rgba"):
            report.info(
                "不透明度",
                "{0}の不透明度を rgba() 色として畳み込みました".format(what),
                "点レイヤは不透明度の対応キーが無いための措置です（定義書 付録B #8）。")
    else:
        p.color = color_to_hex(color)
        p.opacity = clamp01(base_opacity * color_alpha(color))

    # サイズ（QGISのマーカーサイズは「幅」なので半径は 1/2）
    try:
        size_px = _px(symbol.size(), symbol.sizeUnit(), opts, report,
                      "{0}のサイズ".format(what))
        if size_px is not None:
            p.radius = round_px(_scale(size_px, 0.5), 2, minimum=1.0)
    except Exception:
        pass

    sl = _first_layer(symbol)
    if sl is None:
        return p

    cls = _class_name(sl)

    if cls == "QgsSimpleMarkerSymbolLayer":
        # 円以外の形状はMapLibreのcircleでは再現できない
        try:
            shape_name = _marker_shape_name(sl)
            if shape_name and shape_name not in _SIMPLE_MARKER_CIRCLE_SHAPES:
                report.approx(
                    "マーカー形状",
                    "{0}の形状『{1}』は円として近似しました".format(what, shape_name),
                    "MapLibreのcircleレイヤは円のみ描画します。"
                    "形状を保持したい場合はベクトルタイル＋アイコン運用が必要です。")
        except Exception:
            pass
    elif cls == "QgsGeometryGeneratorSymbolLayer":
        report.warn(
            "ジオメトリジェネレータ",
            "{0}がジオメトリジェネレータのため変換できません".format(what),
            "描画時に形状を生成する仕組みはMapLibreにありません。"
            "QGIS側でジオメトリを実体化してから出力してください。")
    elif cls in ("QgsSvgMarkerSymbolLayer", "QgsRasterMarkerSymbolLayer",
                 "QgsAnimatedMarkerSymbolLayer"):
        report.warn(
            "マーカー形状",
            "{0}が画像マーカー（{1}）のため、円で代替しました".format(what, cls))
    elif cls == "QgsFontMarkerSymbolLayer":
        report.warn("マーカー形状",
                    "{0}がフォントマーカーのため、円で代替しました".format(what))
    elif cls == "QgsEllipseSymbolLayer":
        report.approx("マーカー形状",
                      "{0}が楕円マーカーのため、円で近似しました".format(what))

    # 回転
    try:
        if abs(float(symbol.angle())) > 1e-6:
            report.warn("マーカー回転",
                        "{0}に回転角が設定されていますが変換できません".format(what))
    except Exception:
        pass

    # 縁取り
    for attr_c, attr_w, attr_u in (("strokeColor", "strokeWidth", "strokeWidthUnit"),
                                   ("outlineColor", "outlineWidth", "outlineWidthUnit")):
        if hasattr(sl, attr_c):
            try:
                sc = getattr(sl, attr_c)()
                p.stroke_color = (rgba_color(sc, base_opacity) if _allow(opts)
                                  else color_to_hex(sc))
                p.stroke_opacity = clamp01(base_opacity * color_alpha(sc))
            except Exception:
                pass
        if hasattr(sl, attr_w):
            try:
                unit = getattr(sl, attr_u)() if hasattr(sl, attr_u) else None
                w = _px(getattr(sl, attr_w)(), unit, opts, report,
                        "{0}の縁取り幅".format(what))
                p.stroke_width = round_px(w, 2, minimum=0.0)
            except Exception:
                pass
        if p.stroke_color is not None:
            break

    # 縁取りが「なし」なら幅0にする
    try:
        if hasattr(sl, "strokeStyle"):
            from qgis.PyQt.QtCore import Qt as _Qt
            if sl.strokeStyle() == _Qt.NoPen:
                p.stroke_width = 0.0
            elif is_hairline(_call(sl, "strokeWidth"),
                             lambda: sl.strokeStyle()):
                p.stroke_hairline = True
    except Exception:
        pass

    _apply_data_defined(p, sl, symbol, "Point", opts, report, what)
    return p


def _marker_shape_name(symbol_layer):
    """QgsSimpleMarkerSymbolLayer.shape() を名前文字列にする。"""
    try:
        from qgis.core import QgsSimpleMarkerSymbolLayerBase
        return str(QgsSimpleMarkerSymbolLayerBase.encodeShape(symbol_layer.shape()))
    except Exception:
        return ""


# --------------------------------------------------------------------- #
# ライン（線）
# --------------------------------------------------------------------- #
def _simple_line_layers(symbol):
    """シンボル内の SimpleLine レイヤを (index, layer, 幅) で列挙する。"""
    out = []
    try:
        count = symbol.symbolLayerCount()
    except Exception:
        return out
    for index in range(count):
        try:
            layer = symbol.symbolLayer(index)
        except Exception:
            continue
        if _class_name(layer) != "QgsSimpleLineSymbolLayer":
            continue
        try:
            enabled = layer.enabled()
        except Exception:
            enabled = True
        if enabled is False:
            continue
        out.append((index, layer, _call(layer, "width") or 0.0))
    return out


def _pick_line_layers(symbol, opts, report, what):
    """(中心線のレイヤ, 縁取りのレイヤ or None) を返す。

    道路記号のように「太い線の上に細い線を重ねて縁取りを作る」構成は、
    QGISでは1シンボル内に複数の SimpleLine を積んで表現する
    （あるいは同じ条件のスタイルを2枚並べる）。
    先頭1枚だけを見ると**縁取りだけが残って中心線が消える**ので、
    いちばん上を中心線、その下でいちばん太いものを縁取りとして拾う。
    """
    layers = _simple_line_layers(symbol)
    if len(layers) < 2:
        _check_layer_count(symbol, report, what)
        return _first_layer(symbol), None

    top = layers[-1]
    below = layers[:-1]
    widest = max(below, key=lambda item: item[2])
    if widest[2] <= top[2]:
        # 上のほうが太い＝縁取り構成ではない。従来どおり先頭のみ。
        _check_layer_count(symbol, report, what)
        return _first_layer(symbol), None

    report.info(
        "シンボル",
        "{0}が複数の線の重ね描き（縁取り＋中心線）だったため、"
        "縁取りとして再現します".format(what),
        "いちばん上の細い線を中心線、その下でいちばん太い線を縁取り"
        "（casing）として出力します。MapLibre 側では太い線のレイヤを"
        "下に敷いて同じ見た目にします。")
    return top[1], widest[1]


def line_props(symbol, opts, report, what="線シンボル"):
    """QgsLineSymbol → SymbolProps（color / width / opacity）。"""
    p = SymbolProps()
    if symbol is None:
        return p

    base_opacity = _symbol_opacity(symbol)

    # 複数のシンプルラインが重なっていれば「縁取り＋中心線」構成とみなす。
    # QGISは定義順に描く（後のレイヤが上）ので、
    #   いちばん上（最後）＝中心線、それより下で最も太いもの＝縁取り
    # として扱う。1枚だけなら従来どおり。
    sl, casing_layer = _pick_line_layers(symbol, opts, report, what)

    # 色は**採用したシンボルレイヤ**から取る。
    # QgsLineSymbol.color() は先頭レイヤの色を返すため、縁取り構成では
    # 下に敷く縁取りの色になってしまう（中心線の色が失われる）。
    color = parse_line_color(sl)
    if color is None or not color.isValid():
        try:
            color = symbol.color()
        except Exception:
            color = None
    p.color = color_to_hex(color)
    p.opacity = clamp01(base_opacity * color_alpha(color))

    # 線幅はシンボルレイヤ側を優先して読む（line_width_and_unit 参照）。
    raw_w, w_unit = line_width_and_unit(symbol, sl)
    if raw_w is None:
        report.warn(
            "線幅",
            "{0}の線幅を読み取れませんでした（既定値のままになります）".format(what),
            "QgsLineSymbol / QgsLineSymbolLayer のどちらからも幅が取れません。")
    else:
        try:
            w = _px(raw_w, w_unit, opts, report, "{0}の線幅".format(what))
            p.width = round_px(w, 2, minimum=0.0)
        except Exception:
            pass
        if sl is not None and is_hairline(
                raw_w, lambda: _call(sl, "penStyle")):
            p.hairline = True

    if sl is None:
        return p

    cls = _class_name(sl)

    if cls == "QgsSimpleLineSymbolLayer":
        p.dasharray, p.dash_base_width = dash_pattern(
            sl, symbol, opts, report, what)
        try:
            if sl.offset():
                report.warn("線オフセット",
                            "{0}のオフセット指定は変換できません".format(what))
        except Exception:
            pass
    elif cls == "QgsGeometryGeneratorSymbolLayer":
        report.warn(
            "ジオメトリジェネレータ",
            "{0}がジオメトリジェネレータのため変換できません".format(what),
            "描画時に形状を生成する仕組みはMapLibreにありません。")
    elif cls in ("QgsMarkerLineSymbolLayer", "QgsHashedLineSymbolLayer"):
        report.warn(
            "線種",
            "{0}がマーカーライン／ハッチライン（{1}）のため、単純な実線に置き換えました"
            .format(what, cls))
    elif cls == "QgsArrowSymbolLayer":
        report.warn("線種",
                    "{0}が矢印シンボルのため、単純な実線に置き換えました".format(what))
    elif cls in ("QgsInterpolatedLineSymbolLayer",):
        report.warn("線種",
                    "{0}が補間ラインのため、単純な実線に置き換えました".format(what))

    if casing_layer is not None:
        raw_cw, cw_unit = line_width_and_unit(None, casing_layer)
        try:
            cw = _px(raw_cw, cw_unit, opts, report,
                     "{0}の縁取り幅".format(what))
            p.casing_width = round_px(cw, 2, minimum=0.0)
        except Exception:
            p.casing_width = None
        p.casing_color = color_to_hex(
            parse_line_color(casing_layer)) or p.color

    _apply_data_defined(p, sl, symbol, "LineString", opts, report, what)
    return p


def parse_line_color(symbol_layer):
    """SimpleLine の線色（QColor）。取れなければ None。

    無効な QColor を返すゲッターがあるため、**有効な色**が返るまで試す。
    """
    for name in ("color", "strokeColor"):
        value = _call(symbol_layer, name)
        try:
            if value is not None and value.isValid():
                return value
        except AttributeError:
            continue
    return None


# --------------------------------------------------------------------- #
# フィル（面）
# --------------------------------------------------------------------- #
def fill_props(symbol, opts, report, what="面シンボル"):
    """QgsFillSymbol → SymbolProps（color / opacity / stroke_*）。"""
    p = SymbolProps()
    if symbol is None:
        return p

    _check_layer_count(symbol, report, what)
    base_opacity = _symbol_opacity(symbol)

    sl = _first_layer(symbol)
    cls = _class_name(sl)

    fill_color = None
    if sl is not None and hasattr(sl, "fillColor"):
        try:
            fill_color = sl.fillColor()
        except Exception:
            fill_color = None
    if fill_color is None:
        try:
            fill_color = symbol.color()
        except Exception:
            fill_color = None

    # --- 塗りの種類ごとの近似 -------------------------------------- #
    if cls == "QgsGradientFillSymbolLayer":
        try:
            p.color = blend_colors(sl.color(), sl.color2())
            fill_color = sl.color()
        except Exception:
            p.color = color_to_hex(fill_color)
        report.approx(
            "塗り",
            "{0}がグラデーション塗りのため、2色の中間色で近似しました".format(what),
            "MapLibreの fill-color は単色のみです。")
    elif cls == "QgsShapeburstFillSymbolLayer":
        try:
            p.color = blend_colors(sl.color(), sl.color2())
        except Exception:
            p.color = color_to_hex(fill_color)
        report.approx("塗り",
                      "{0}がシェイプバースト塗りのため、中間色で近似しました".format(what))
    elif cls == "QgsGeometryGeneratorSymbolLayer":
        p.color = color_to_hex(fill_color)
        report.warn(
            "ジオメトリジェネレータ",
            "{0}がジオメトリジェネレータのため変換できません".format(what),
            "描画時に形状を生成する仕組みはMapLibreにありません。"
            "QGIS側でジオメトリを実体化してから出力してください。")
    elif cls in ("QgsSVGFillSymbolLayer", "QgsLinePatternFillSymbolLayer",
                 "QgsPointPatternFillSymbolLayer", "QgsRasterFillSymbolLayer",
                 "QgsRandomMarkerFillSymbolLayer"):
        p.color = color_to_hex(fill_color)
        report.warn(
            "塗り",
            "{0}がパターン塗り（{1}）のため、単色に置き換えました".format(what, cls))
    else:
        p.color = color_to_hex(fill_color)

    p.opacity = clamp01(base_opacity * color_alpha(fill_color))

    # ハッチング（ブラシスタイル）
    if sl is not None and hasattr(sl, "brushStyle"):
        try:
            from qgis.PyQt.QtCore import Qt as _Qt
            bs = sl.brushStyle()
            if bs == _Qt.NoBrush:
                p.opacity = 0.0
                report.info("塗り", "{0}は塗りなし指定のため fill-opacity=0 にしました"
                            .format(what))
            elif bs != _Qt.SolidPattern:
                report.approx(
                    "塗り",
                    "{0}がハッチングパターン指定のため、ベタ塗りに近似しました".format(what))
        except Exception:
            pass

    # --- 外周線 ------------------------------------------------------ #
    if sl is not None:
        if hasattr(sl, "strokeColor"):
            try:
                sc = sl.strokeColor()
                p.stroke_color = color_to_hex(sc)
                p.stroke_opacity = clamp01(base_opacity * color_alpha(sc))
            except Exception:
                pass
        if hasattr(sl, "strokeWidth"):
            try:
                unit = sl.strokeWidthUnit() if hasattr(sl, "strokeWidthUnit") else None
                w = _px(sl.strokeWidth(), unit, opts, report,
                        "{0}の外周線幅".format(what))
                p.stroke_width = round_px(w, 2, minimum=0.0)
            except Exception:
                pass
        if hasattr(sl, "strokeStyle"):
            try:
                from qgis.PyQt.QtCore import Qt as _Qt
                if sl.strokeStyle() == _Qt.NoPen:
                    p.stroke_width = 0.0
                    p.stroke_opacity = 0.0
                elif is_hairline(_call(sl, "strokeWidth"),
                                 lambda: sl.strokeStyle()):
                    # 「非常に細い線」＝幅0のヘアライン。消さずに細線として描く
                    p.stroke_hairline = True
                if sl.strokeStyle() not in (_Qt.NoPen, _Qt.SolidLine):
                    # 外周線の破線: strokeStyle を penStyle 相当として扱う
                    p.dasharray = _outline_dash_pattern(sl, p, opts, report, what)
            except Exception:
                pass

    _apply_data_defined(p, sl, symbol, "Polygon", opts, report, what)
    return p


# --------------------------------------------------------------------- #
def _outline_dash_pattern(symbol_layer, props, opts, report, what):
    """面の外周線の線種 → line-dasharray。

    外周線は `strokeStyle()`（QPen スタイル）で指定されるため、線種名を
    引いて Qt 既定パターンへ対応させる。線幅の倍数表現なので幅で割る必要はない。
    """
    try:
        from qgis.PyQt.QtCore import Qt as _Qt
    except ImportError:
        return []
    try:
        style = symbol_layer.strokeStyle()
    except Exception:
        return []
    for name, pattern in _QT_PEN_DASH.items():
        if getattr(_Qt, name, None) == style:
            report.info(
                "外周線",
                "{0}の外周線の線種『{1}』を line-dasharray {2} へ変換しました"
                .format(what, name, pattern))
            return list(pattern)
    report.approx("外周線",
                  "{0}の外周線の線種を判別できず実線にしました".format(what))
    return []


def _apply_data_defined(props, symbol_layer, symbol, geom, opts, report, what):
    """データ定義プロパティ由来の式を SymbolProps へ反映する。"""
    if symbol_layer is None:
        return
    ddefs = data_defined_expressions(symbol_layer, opts, report, what)
    if not ddefs:
        return

    if "color" in ddefs:
        props.color = ddefs["color"]
    if "stroke_color" in ddefs:
        props.stroke_color = ddefs["stroke_color"]

    if geom == "Point":
        if "size" in ddefs:
            unit = None
            try:
                unit = symbol.sizeUnit()
            except Exception:
                pass
            size_px = _px(ddefs["size"], unit, opts, report,
                          "{0}のサイズ（データ定義）".format(what))
            props.radius = _scale(size_px, 0.5)
        if "stroke_width" in ddefs:
            unit = None
            try:
                unit = symbol_layer.strokeWidthUnit()
            except Exception:
                pass
            props.stroke_width = _px(ddefs["stroke_width"], unit, opts, report,
                                     "{0}の縁取り幅（データ定義）".format(what))
    elif geom == "LineString":
        key = "width" if "width" in ddefs else "stroke_width"
        if key in ddefs:
            unit = None
            try:
                unit = symbol.widthUnit()
            except Exception:
                pass
            props.width = _px(ddefs[key], unit, opts, report,
                              "{0}の線幅（データ定義）".format(what))
    else:  # Polygon
        if "stroke_width" in ddefs:
            unit = None
            try:
                unit = symbol_layer.strokeWidthUnit()
            except Exception:
                pass
            props.stroke_width = _px(ddefs["stroke_width"], unit, opts, report,
                                     "{0}の外周線幅（データ定義）".format(what))

    if "opacity" in ddefs:
        # QGISのalphaは 0–100 または 0–1。式のままでは判別できないため
        # MapLibre 側では 0–1 とみなす。
        props.opacity = ddefs["opacity"]
        if geom == "Point":
            report.warn(
                "データ定義",
                "{0}の不透明度のデータ定義は点レイヤでは反映できません".format(what))
            props.opacity = 1.0


def props_for_geom(symbol, geom, opts, report, what):
    """幾何種別に応じて適切な抽出関数を呼ぶ。"""
    if symbol is None:
        return SymbolProps()
    if geom == "Point":
        return marker_props(symbol, opts, report, what)
    if geom == "LineString":
        return line_props(symbol, opts, report, what)
    return fill_props(symbol, opts, report, what)
