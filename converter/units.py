# -*- coding: utf-8 -*-
"""単位・色・縮尺の換算ユーティリティ。

MapLibre GL JS は CSS ピクセル基準なので、QGIS の mm / pt / inch /
マップ単位で指定された寸法をすべてピクセルへ落とす必要がある。
"""

import math

try:
    from qgis.core import QgsUnitTypes
except ImportError:      # QGIS外（テスト時）でもimportできるようにする
    QgsUnitTypes = None

# WebMercator z=0 の解像度（赤道上・m/px）
EARTH_CIRCUMFERENCE = 40075016.686
BASE_RESOLUTION = EARTH_CIRCUMFERENCE / 256.0   # 156543.033928...
INCH_IN_METERS = 0.0254
MM_PER_INCH = 25.4
POINTS_PER_INCH = 72.0

MAX_ZOOM = 24.0
MIN_ZOOM = 0.0


# --------------------------------------------------------------------- #
# 単位 → ピクセル
# --------------------------------------------------------------------- #
def encode_render_unit(unit):
    """QgsUnitTypes.RenderUnit を安定した文字列コードへ。

    QGIS 3.30 で enum が Qgis.RenderUnit へ移ったため、直接の enum 比較では
    なく encodeUnit() の戻り値（'MM' / 'Point' / 'Pixel' / 'MapUnit' /
    'RenderMetersInMapUnit' / 'Percentage' / 'Inch'）で判定する。
    """
    if QgsUnitTypes is None or unit is None:
        return "Pixel"
    try:
        return str(QgsUnitTypes.encodeUnit(unit))
    except Exception:
        return "Pixel"


def meters_per_pixel(zoom, latitude):
    """WebMercatorの指定ズーム・緯度における地上分解能（m/px）。"""
    lat = max(min(float(latitude), 85.0), -85.0)
    return (BASE_RESOLUTION * math.cos(math.radians(lat))) / (2.0 ** float(zoom))


def to_pixels(value, unit, opts, report=None, what=""):
    """QGISの寸法値をCSSピクセルへ換算する。

    戻り値: float（ピクセル）
    換算が厳密でないもの（マップ単位・パーセント）は report に近似として記録する。
    """
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None

    code = encode_render_unit(unit)
    dpi = opts.dpi

    if code == "Pixel":
        return value
    if code == "MM":
        return value * dpi / MM_PER_INCH
    if code == "Point":
        return value * dpi / POINTS_PER_INCH
    if code == "Inch":
        return value * dpi
    if code in ("MapUnit", "RenderMetersInMapUnit", "MetersInMapUnits"):
        # マップ単位はズームに依存するため固定pxにはできない。
        # 基準ズーム・基準緯度での実寸換算で近似する。
        mpp = meters_per_pixel(opts.reference_zoom, opts.reference_latitude)
        px = value / mpp if mpp else value
        if report is not None:
            report.approx(
                "単位",
                "{0}がマップ単位指定のため、ズーム{1:g}・緯度{2:g}°での実寸として"
                "{3:.2f}px に近似しました".format(
                    what or "寸法", opts.reference_zoom,
                    opts.reference_latitude, px),
                "MapLibre側は固定ピクセル指定のため、他ズームでは見た目が変わります。")
        return px
    if code == "Percentage":
        if report is not None:
            report.warn("単位",
                        "{0}がパーセント指定のため換算できません".format(what or "寸法"))
        return None

    if report is not None:
        report.warn("単位", "未知の単位 '{0}' のため {1} を換算できません".format(
            code, what or "寸法"))
    return None


# --------------------------------------------------------------------- #
# 色
# --------------------------------------------------------------------- #
def color_to_hex(qcolor):
    """QColor → '#rrggbb'（アルファは落とす）。"""
    if qcolor is None:
        return None
    try:
        if not qcolor.isValid():
            return None
        return "#{0:02x}{1:02x}{2:02x}".format(
            qcolor.red(), qcolor.green(), qcolor.blue())
    except AttributeError:
        return None


def color_alpha(qcolor):
    """QColor のアルファを 0.0–1.0 で返す。無効なら 1.0。"""
    if qcolor is None:
        return 1.0
    try:
        if not qcolor.isValid():
            return 1.0
        return float(qcolor.alpha()) / 255.0
    except AttributeError:
        return 1.0


def rgba_color(qcolor, extra_opacity=1.0):
    """QColor（＋追加の不透明度）→ CSS色文字列。

    不透明なら '#rrggbb'、半透明なら 'rgba(r,g,b,a)' を返す。
    MapLibre はどちらも受け付けるため、`.fgstyle` の色キーに
    そのまま入れれば不透明度をシンボル色へ畳み込める。
    """
    if qcolor is None:
        return None
    try:
        if not qcolor.isValid():
            return None
    except AttributeError:
        return None
    alpha = color_alpha(qcolor) * float(extra_opacity if extra_opacity is not None else 1.0)
    alpha = max(0.0, min(1.0, alpha))
    if alpha >= 0.999:
        return color_to_hex(qcolor)
    return "rgba({0},{1},{2},{3:g})".format(
        qcolor.red(), qcolor.green(), qcolor.blue(), round(alpha, 3))


def blend_colors(c1, c2):
    """2色の中間色を返す（グラデーション塗りの近似用）。"""
    try:
        return "#{0:02x}{1:02x}{2:02x}".format(
            (c1.red() + c2.red()) // 2,
            (c1.green() + c2.green()) // 2,
            (c1.blue() + c2.blue()) // 2)
    except AttributeError:
        return color_to_hex(c1)


def meters_to_pixels_expression(meters_or_expr, opts):
    """地上メートル指定の寸法を、ズーム依存のMapLibre式へ変換する。

        px(z) = meters × 2^z ÷ (156543.034 × cos(lat))

    2の指数関数なので `["interpolate", ["exponential", 2], ["zoom"], …]` の
    2点指定で全ズームにわたり厳密に一致する（ForestGeo Studio 本体の
    `_tree_circle_radius_expr()` と同じ考え方）。
    """
    def factor(zoom):
        mpp = meters_per_pixel(zoom, opts.reference_latitude)
        return (1.0 / mpp) if mpp else 0.0

    def at(zoom):
        f = factor(zoom)
        if isinstance(meters_or_expr, (int, float)):
            return round(meters_or_expr * f, 4)
        return ["*", meters_or_expr, f]

    return ["interpolate", ["exponential", 2], ["zoom"],
            0, at(0.0), 24, at(24.0)]


def unit_scale_factor(unit, opts):
    """単位 → ピクセル換算の定数倍率。定数で表せない単位は None。"""
    code = encode_render_unit(unit)
    if code == "Pixel":
        return 1.0
    if code == "MM":
        return opts.dpi / MM_PER_INCH
    if code == "Point":
        return opts.dpi / POINTS_PER_INCH
    if code == "Inch":
        return float(opts.dpi)
    return None


def to_pixels_expression(value_or_expr, unit, opts, report=None, what=""):
    """スカラーでも式でも受け取り、ピクセル値（または式）を返す。

    マップ単位の場合はズーム依存の式になるため、固定ピクセルへ潰さずに
    実寸のまま表現できる（`allow_expressions` が有効なときのみ）。
    """
    if value_or_expr is None:
        return None

    code = encode_render_unit(unit)
    factor = unit_scale_factor(unit, opts)

    if factor is not None:
        if isinstance(value_or_expr, (int, float)):
            return float(value_or_expr) * factor
        if factor == 1.0:
            return value_or_expr
        return ["*", value_or_expr, factor]

    if code in ("MapUnit", "RenderMetersInMapUnit", "MetersInMapUnits"):
        if getattr(opts, "allow_expressions", False):
            if report is not None:
                report.info(
                    "単位",
                    "{0}がマップ単位指定のため、ズーム依存の式で実寸を再現しました"
                    .format(what or "寸法"),
                    "MapLibre の interpolate(exponential 2) により、"
                    "全ズームで地上の実寸に一致します。")
            return meters_to_pixels_expression(value_or_expr, opts)
        # 式を使わない設定なら従来どおり基準ズームでの固定px近似
        return to_pixels(value_or_expr, unit, opts, report, what)

    if report is not None:
        report.warn("単位", "{0}の単位『{1}』は換算できません".format(
            what or "寸法", code))
    return None


# --------------------------------------------------------------------- #
# 縮尺 ↔ ズーム
# --------------------------------------------------------------------- #
def zoom_to_scale(zoom, opts):
    """WebMercatorズーム → 縮尺分母。"""
    return meters_per_pixel(zoom, opts.reference_latitude) * opts.dpi / INCH_IN_METERS


def scale_to_zoom(scale_denominator, opts):
    """縮尺分母 → WebMercatorズーム。

    scale = (156543.034 * cos(lat) / 2^z) * dpi / 0.0254
      ⇔  z = log2( 156543.034 * cos(lat) * dpi / 0.0254 / scale )
    """
    try:
        scale = float(scale_denominator)
    except (TypeError, ValueError):
        return None
    if scale <= 0:
        return None
    k = zoom_to_scale(0.0, opts)     # z=0 のときの縮尺分母
    if k <= 0:
        return None
    return math.log2(k / scale)


def clamp_zoom(z):
    if z is None:
        return None
    return max(MIN_ZOOM, min(MAX_ZOOM, float(z)))


def scale_range_to_zoom_range(min_scale, max_scale, opts):
    """QGISの縮尺範囲 → (minzoom, maxzoom)。

    QGISの用語：
      minimumScale = 最小縮尺 = 最も引いた側の限界（分母が大きい）
      maximumScale = 最大縮尺 = 最も寄った側の限界（分母が小さい）
    どちらも 0 は「制限なし」を意味する。
    """
    z_min = scale_to_zoom(min_scale, opts)
    z_max = scale_to_zoom(max_scale, opts)

    minzoom = MIN_ZOOM if z_min is None else clamp_zoom(z_min)
    maxzoom = MAX_ZOOM if z_max is None else clamp_zoom(z_max)

    if minzoom > maxzoom:
        minzoom, maxzoom = maxzoom, minzoom

    if opts.round_zoom:
        # 見えすぎないよう内側に丸める
        minzoom = clamp_zoom(math.ceil(minzoom))
        maxzoom = clamp_zoom(math.floor(maxzoom))
        if minzoom > maxzoom:
            maxzoom = minzoom
    else:
        minzoom = round(minzoom, 2)
        maxzoom = round(maxzoom, 2)

    return minzoom, maxzoom


# --------------------------------------------------------------------- #
# 数値整形
# --------------------------------------------------------------------- #
def is_expression(value):
    """MapLibre式（配列・オブジェクト）かどうか。"""
    return isinstance(value, (list, dict))


def round_px(value, ndigits=2, minimum=None, maximum=None):
    """ピクセル値を丸めて範囲に収める。式はそのまま通す。"""
    if value is None or is_expression(value):
        return value
    v = round(float(value), ndigits)
    if minimum is not None:
        v = max(minimum, v)
    if maximum is not None:
        v = min(maximum, v)
    return v


def round_int(value, minimum=None, maximum=None):
    if value is None or is_expression(value):
        return value
    v = int(round(float(value)))
    if minimum is not None:
        v = max(minimum, v)
    if maximum is not None:
        v = min(maximum, v)
    return v


def clamp01(value, ndigits=3):
    if value is None or is_expression(value):
        return value
    return round(max(0.0, min(1.0, float(value))), ndigits)


def num_or_str(value):
    """凡例・ルール値として使いやすい形へ。整数相当のfloatはintにする。"""
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value
