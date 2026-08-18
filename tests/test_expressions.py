# -*- coding: utf-8 -*-
"""式トランスレータと高度な出力パスのテスト（QGIS不要）。

実行:
    python3 -m fgstyle_maker.tests.test_expressions
"""

import os
import sys
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from fgstyle_maker.tests import qgis_stub          # noqa: E402
qgis_stub.install()

from PyQt5.QtXml import QDomDocument               # noqa: E402

from fgstyle_maker.converter import mlexpr         # noqa: E402
from fgstyle_maker.converter.features import detect_unsupported   # noqa: E402
from fgstyle_maker.converter.options import ConvertOptions        # noqa: E402
from fgstyle_maker.converter.report import ConversionReport       # noqa: E402
from fgstyle_maker.converter.units import (                       # noqa: E402
    rgba_color, meters_to_pixels_expression, to_pixels_expression,
    meters_per_pixel)
from fgstyle_maker.converter.vector import convert_vector_layer   # noqa: E402
from fgstyle_maker.tests import qml_fixture as F   # noqa: E402

from PyQt5.QtGui import QColor                     # noqa: E402


def _report():
    rep = ConversionReport()
    return rep, rep.layer("テスト")


def _fill(color="45,138,78,255", outline_style="solid", outline_width="0.26",
          alpha="1"):
    return F.Symbol(ET.fromstring(
        '<symbol type="fill" alpha="{a}"><layer class="SimpleFill">'
        '<Option type="Map">'
        '<Option name="color" value="{c}"/>'
        '<Option name="outline_color" value="255,255,255,255"/>'
        '<Option name="outline_style" value="{os}"/>'
        '<Option name="outline_width" value="{ow}"/>'
        '<Option name="outline_width_unit" value="MM"/>'
        '<Option name="style" value="solid"/>'
        '</Option></layer></symbol>'.format(a=alpha, c=color, os=outline_style,
                                            ow=outline_width)))


def _marker(color="230,57,70,255", size="4", size_unit="MM", alpha="1"):
    return F.Symbol(ET.fromstring(
        '<symbol type="marker" alpha="{a}"><layer class="SimpleMarker">'
        '<Option type="Map">'
        '<Option name="color" value="{c}"/>'
        '<Option name="name" value="Circle"/>'
        '<Option name="size" value="{s}"/>'
        '<Option name="size_unit" value="{u}"/>'
        '<Option name="outline_color" value="255,255,255,255"/>'
        '<Option name="outline_width" value="0.2"/>'
        '<Option name="outline_width_unit" value="MM"/>'
        '</Option></layer></symbol>'.format(a=alpha, c=color, s=size, u=size_unit)))


class _Rule(object):
    def __init__(self, expr, symbol, label="", min_scale=0, max_scale=0):
        self._e, self._s, self._l = expr, symbol, label
        self._mn, self._mx = min_scale, max_scale

    def filterExpression(self): return self._e
    def symbol(self): return self._s
    def label(self): return self._l
    def children(self): return []
    def active(self): return True
    def isElse(self): return self._e.strip().lower() in ("else", "")
    def minimumScale(self): return self._mn
    def maximumScale(self): return self._mx


class _RuleRenderer(object):
    def __init__(self, rules): self._r = rules
    def type(self): return "RuleRenderer"

    def rootRule(self):
        rules = self._r
        return type("Root", (), {"children": lambda s: rules})()


# ===================================================================== #
class TestTranslator(unittest.TestCase):

    def t(self, text):
        return mlexpr.translate(text)

    def test_comparison(self):
        self.assertEqual(self.t('"a" = 1'), ["==", ["get", "a"], 1])
        self.assertEqual(self.t('"a" <> 1'), ["!=", ["get", "a"], 1])
        self.assertEqual(self.t('"a" >= 1.5'), [">=", ["get", "a"], 1.5])

    def test_bare_field(self):
        self.assertEqual(self.t("ser = 619"), ["==", ["get", "ser"], 619])

    def test_and_or_flatten(self):
        self.assertEqual(self.t('"a" = 1 AND "b" = 2 AND "c" = 3'),
                         ["all", ["==", ["get", "a"], 1],
                          ["==", ["get", "b"], 2], ["==", ["get", "c"], 3]])
        self.assertEqual(self.t('"a" = 1 OR "b" = 2')[0], "any")

    def test_precedence_and_binds_tighter_than_or(self):
        got = self.t('"a" = 1 OR "b" = 2 AND "c" = 3')
        self.assertEqual(got[0], "any")
        self.assertEqual(got[2][0], "all")

    def test_not(self):
        self.assertEqual(self.t('NOT "a" = 1'), ["!", ["==", ["get", "a"], 1]])

    def test_is_null(self):
        self.assertEqual(self.t('"a" IS NULL'), ["==", ["get", "a"], None])
        self.assertEqual(self.t('"a" IS NOT NULL'),
                         ["!", ["==", ["get", "a"], None]])

    def test_in_and_not_in(self):
        self.assertEqual(self.t('"a" IN (1,2)'),
                         ["in", ["get", "a"], ["literal", [1, 2]]])
        self.assertEqual(self.t('"a" NOT IN (1)')[0], "!")

    def test_between(self):
        self.assertEqual(self.t('"a" BETWEEN 1 AND 5'),
                         ["all", [">=", ["get", "a"], 1],
                          ["<=", ["get", "a"], 5]])

    def test_arithmetic_precedence(self):
        self.assertEqual(self.t('1 + 2 * 3'), ["+", 1, ["*", 2, 3]])
        self.assertEqual(self.t('(1 + 2) * 3'), ["*", ["+", 1, 2], 3])

    def test_power_is_right_associative(self):
        self.assertEqual(self.t('2 ^ 3 ^ 2'), ["^", 2, ["^", 3, 2]])

    def test_case_when(self):
        self.assertEqual(
            self.t("CASE WHEN \"a\" > 1 THEN 'x' ELSE 'y' END"),
            ["case", [">", ["get", "a"], 1], "x", "y"])

    def test_case_without_else_gets_null(self):
        self.assertEqual(self.t("CASE WHEN \"a\" > 1 THEN 'x' END")[-1], None)

    def test_string_escape(self):
        self.assertEqual(self.t("'it''s'"), "it's")

    def test_concat_operator_and_function_agree(self):
        self.assertEqual(self.t('"a" || "b"'), self.t('concat("a", "b")'))

    def test_substr_is_one_based(self):
        self.assertEqual(self.t('substr("a", 1, 2)'),
                         ["slice", ["to-string", ["get", "a"]], 0, ["+", 0, 2]])

    def test_quoted_field_with_spaces(self):
        self.assertEqual(self.t('"林 齢" > 1'), [">", ["get", "林 齢"], 1])

    def test_unsupported_raises(self):
        for bad in ('area($geometry)', 'regexp_match("a", \'x\')',
                    '@layer_name', 'sum("a")', '"a" LIKE \'x%\'',
                    'unknown_fn(1)', '"a" +'):
            with self.subTest(expr=bad):
                self.assertRaises(mlexpr.UnsupportedExpression,
                                  mlexpr.translate, bad)

    def test_try_translate_returns_reason(self):
        expr, err = mlexpr.try_translate('sum("a")')
        self.assertIsNone(expr)
        self.assertIn("集計関数", err)

    def test_collect_fields(self):
        expr = mlexpr.translate('"a" = 1 AND "b" > "c"')
        self.assertEqual(sorted(mlexpr.collect_fields(expr)), ["a", "b", "c"])


# ===================================================================== #
class TestUnitExpressions(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions(reference_latitude=35.0)
        self.rep, self.lrep = _report()

    def test_rgba_is_used_only_when_translucent(self):
        self.assertEqual(rgba_color(QColor(255, 0, 0, 255)), "#ff0000")
        self.assertEqual(rgba_color(QColor(255, 0, 0, 128)),
                         "rgba(255,0,0,0.502)")
        self.assertEqual(rgba_color(QColor(255, 0, 0, 255), 0.5),
                         "rgba(255,0,0,0.5)")

    def test_map_unit_becomes_zoom_expression(self):
        expr = to_pixels_expression(10.0, "MapUnit", self.opts, self.lrep, "線幅")
        self.assertEqual(expr[0], "interpolate")
        self.assertEqual(expr[1], ["exponential", 2])
        self.assertEqual(expr[2], ["zoom"])

    def test_zoom_expression_is_exact_at_both_stops(self):
        """2点の値が各ズームでの実寸ピクセルと一致すること。"""
        expr = meters_to_pixels_expression(100.0, self.opts)
        for zoom, index in ((0.0, 4), (24.0, 6)):
            expected = 100.0 / meters_per_pixel(zoom, self.opts.reference_latitude)
            self.assertAlmostEqual(expr[index], expected, places=3)

    def test_mm_stays_scalar(self):
        value = to_pixels_expression(1.0, "MM", self.opts, self.lrep, "線幅")
        self.assertAlmostEqual(value, 96 / 25.4, places=4)

    def test_expression_input_is_scaled(self):
        value = to_pixels_expression(["get", "w"], "MM", self.opts, self.lrep, "")
        self.assertEqual(value[0], "*")
        self.assertEqual(value[1], ["get", "w"])

# ===================================================================== #
class TestRuleBasedExpressionPath(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def _convert(self, rules, geom="Polygon", opts=None):
        renderer = _RuleRenderer(rules)
        return convert_vector_layer(F.FakeLayer(renderer), geom,
                                    opts or self.opts, self.lrep)

    def test_simple_rules_still_use_color_rules(self):
        """単一フィールドの単純な条件は従来どおり vt-color-rules。"""
        style = self._convert([_Rule('"a" = \'x\'', _fill(), "X"),
                               _Rule('"a" = \'y\'', _fill(), "Y")])
        self.assertTrue(style["vt-color-rule-enabled"])
        self.assertNotIn("vt-legend", style)
        self.assertIsInstance(style["fill-color"], str)

    def test_multi_field_condition_uses_case_expression(self):
        style = self._convert([
            _Rule('"樹種" = \'スギ\' AND "林齢" > 40', _fill("1,2,3,255"), "高齢スギ"),
            _Rule('ELSE', _fill("204,204,204,255"), "その他")])
        self.assertFalse(style["vt-color-rule-enabled"])
        self.assertEqual(style["fill-color"][0], "case")
        self.assertEqual(style["fill-color"][1],
                         ["all", ["==", ["get", "樹種"], "スギ"],
                          [">", ["get", "林齢"], 40]])

    def test_case_path_writes_legend(self):
        style = self._convert([
            _Rule('"a" = 1 OR "b" = 2', _fill("1,2,3,255"), "条件A"),
            _Rule('ELSE', _fill("9,9,9,255"), "その他")])
        labels = [i["label"] for i in style["vt-legend"]]
        self.assertEqual(labels, ["条件A", "その他"])
        for item in style["vt-legend"]:
            self.assertIsInstance(item["color"], str)
            self.assertTrue(item["color"].startswith("#"))

    def test_case_path_requires_patches(self):
        self._convert([_Rule('"a" = 1 OR "b" = 2', _fill(), "A")])
        self.assertIn("expr-safe", self.lrep.patches)
        self.assertIn("legend", self.lrep.patches)

    def test_rule_scale_range_becomes_zoom_condition(self):
        style = self._convert([
            _Rule('"a" = 1 OR "b" = 2', _fill(), "A", min_scale=50000),
            _Rule('ELSE', _fill(), "他")])
        cond = style["fill-color"][1]
        self.assertEqual(cond[0], "all")
        self.assertTrue(any(isinstance(c, list) and c[1] == ["zoom"]
                            for c in cond[1:]))

    def test_untranslatable_rule_falls_back(self):
        style = self._convert([
            _Rule('area($geometry) > 100', _fill(), "面積大"),
            _Rule('"a" = \'x\'', _fill(), "X")])
        # case式は諦め、変換できるルールだけ色分けルールとして出力される
        self.assertNotIn("vt-legend", style)
        self.assertTrue(style["vt-color-rule-enabled"])

# ===================================================================== #
class TestPerRuleExtras(unittest.TestCase):
    """色分けルールでは表現できない項目の式出力。"""

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def test_point_radius_varies_by_category(self):
        cats = [F.Category("A", _marker(size="3"), "A"),
                F.Category("B", _marker(size="8"), "B")]
        renderer = F.CategorizedRenderer("cls", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Point",
                                     self.opts, self.lrep)
        radius = style["circle-radius"]
        self.assertIsInstance(radius, list)
        self.assertEqual(radius[0], "match")
        self.assertEqual(radius[1], ["to-string", ["coalesce", ["get", "cls"], ""]])

    def test_same_radius_stays_scalar(self):
        cats = [F.Category("A", _marker(size="4"), "A"),
                F.Category("B", _marker(size="4"), "B")]
        renderer = F.CategorizedRenderer("cls", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Point",
                                     self.opts, self.lrep)
        self.assertIsInstance(style["circle-radius"], int)

    def test_graduated_uses_step_for_extras(self):
        ranges = [F.Range(0, 10, _marker(size="3"), "a"),
                  F.Range(10, 20, _marker(size="9"), "b")]
        renderer = F.GraduatedRenderer("h", ranges)
        style = convert_vector_layer(F.FakeLayer(renderer), "Point",
                                     self.opts, self.lrep)
        self.assertEqual(style["circle-radius"][0], "step")

class TestPointOpacity(unittest.TestCase):

    def setUp(self):
        self.rep, self.lrep = _report()

    def test_translucent_marker_becomes_rgba(self):
        renderer = F.SingleRenderer(_marker(alpha="0.5"))
        style = convert_vector_layer(F.FakeLayer(renderer), "Point",
                                     ConvertOptions(),
                                     self.lrep)
        self.assertTrue(style["circle-color"].startswith("rgba("))

    def test_opaque_marker_stays_hex(self):
        renderer = F.SingleRenderer(_marker(alpha="1"))
        style = convert_vector_layer(F.FakeLayer(renderer), "Point",
                                     ConvertOptions(),
                                     self.lrep)
        self.assertTrue(style["circle-color"].startswith("#"))

# ===================================================================== #
class TestFeatureDetection(unittest.TestCase):

    def _detect(self, xml):
        doc = QDomDocument()
        doc.setContent(xml)
        rep, lrep = _report()
        detect_unsupported(doc.documentElement(), lrep)
        return lrep

    def test_blend_mode(self):
        lrep = self._detect('<maplayer><blendMode>5</blendMode></maplayer>')
        self.assertTrue(any("合成モード" in e.category for e in lrep.entries))

    def test_normal_blend_mode_is_silent(self):
        lrep = self._detect('<maplayer><blendMode>0</blendMode></maplayer>')
        self.assertEqual(len(lrep.entries), 0)

    def test_diagram(self):
        lrep = self._detect(
            '<maplayer><LinearlyInterpolatedDiagramRenderer/></maplayer>')
        self.assertTrue(any("ダイアグラム" in e.category for e in lrep.entries))

    def test_temporal(self):
        lrep = self._detect('<maplayer><temporal enabled="1"/></maplayer>')
        self.assertTrue(any("時系列" in e.category for e in lrep.entries))

    def test_paint_effects(self):
        lrep = self._detect(
            '<maplayer><effect type="effectStack">'
            '<effect type="dropShadow"/><effect type="blur"/>'
            '</effect></maplayer>')
        self.assertTrue(any("ペイントエフェクト" in e.category
                            for e in lrep.entries))

    def test_geometry_generator(self):
        lrep = self._detect(
            '<maplayer><layer class="GeometryGenerator"/></maplayer>')
        self.assertTrue(any("ジオメトリジェネレータ" in e.category
                            for e in lrep.entries))

    def test_callout(self):
        lrep = self._detect(
            '<maplayer><labeling type="simple"><settings>'
            '<callout enabled="1"/></settings></labeling></maplayer>')
        self.assertTrue(any("引き出し線" in e.category for e in lrep.entries))

    def test_clean_layer_is_silent(self):
        lrep = self._detect(
            '<maplayer><blendMode>0</blendMode><featureBlendMode>0</featureBlendMode>'
            '<temporal enabled="0"/><renderer-v2 type="singleSymbol"/></maplayer>')
        self.assertEqual(len(lrep.entries), 0)




# ===================================================================== #
class TestNumericRules(unittest.TestCase):
    """数値属性は常に step 式（num_min/num_max）で出力する。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _cats(self):
        return [F.Category(1, _fill("0,0,0,255"), "境界"),
                F.Category(2, _fill("0,0,0,255"), "断層"),
                F.Category(90, _fill("0,0,0,255"), "海岸線")]

    def _convert(self, opts, geom="LineString"):
        renderer = F.CategorizedRenderer("Major_Code", self._cats())
        return convert_vector_layer(F.FakeLayer(renderer), geom, opts, self.lrep)

    def test_auto_emits_numeric_rules(self):
        style = self._convert(ConvertOptions())
        rules = style["vt-color-rules"]
        self.assertTrue(all("num_min" in r for r in rules))
        self.assertEqual([r["num_min"] for r in rules], [1, 2, 90])
        self.assertNotIn("to-string", self.lrep.patches)

    def test_auto_keeps_labels(self):
        style = self._convert(ConvertOptions())
        self.assertEqual([r["label"] for r in style["vt-color-rules"]],
                         ["境界", "断層", "海岸線"])

    def test_string_field_is_unaffected_by_strategy(self):
        cats = [F.Category("スギ", _fill(), "スギ")]
        renderer = F.CategorizedRenderer("樹種", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(),
                                     self.lrep)
        self.assertEqual(style["vt-color-rules"][0]["value"], "スギ")
        self.assertNotIn("num_min", style["vt-color-rules"][0])

    def test_gap_closing_hides_undefined_codes(self):
        style = self._convert(ConvertOptions(close_numeric_gaps=True))
        rules = style["vt-color-rules"]
        self.assertGreater(len(rules), 3)
        hidden = [r for r in rules if r.get("opacity") == 0.0]
        self.assertTrue(hidden)
        self.assertTrue(all(r.get("label") == "" for r in hidden))

    def test_non_numeric_values_fall_back_to_string(self):
        cats = [F.Category(1, _fill(), "A"), F.Category("x", _fill(), "B")]
        renderer = F.CategorizedRenderer("mixed", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(), self.lrep)
        self.assertTrue(all("num_min" not in r for r in style["vt-color-rules"]))


class TestValueHygiene(unittest.TestCase):
    """表記ゆれの検出と、プラグイン側での吸収。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _convert(self, values, opts=None):
        cats = [F.Category(v, _fill(), str(v)) for v in values]
        renderer = F.CategorizedRenderer("cls", cats)
        return convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                    opts or ConvertOptions(), self.lrep)

    def _entries(self, level=None):
        return [e for e in self.lrep.entries
                if e.category == "表記ゆれ" and (level is None or e.level == level)]

    # --- 吸収ON（既定）------------------------------------------------ #
    def test_fullwidth_gets_halfwidth_alias(self):
        style = self._convert(["１２３", "abc"])
        values = [r["value"] for r in style["vt-color-rules"]]
        self.assertIn("１２３", values)
        self.assertIn("123", values)

    def test_alias_shares_color_and_label(self):
        style = self._convert(["１２３"])
        rules = style["vt-color-rules"]
        self.assertEqual(rules[0]["color"], rules[1]["color"])
        self.assertEqual(rules[0].get("label"), rules[1].get("label"))

    def test_fullwidth_space_gets_alias(self):
        style = self._convert(["ス　ギ"])
        self.assertIn("ス ギ", [r["value"] for r in style["vt-color-rules"]])

    def test_padded_value_gets_trimmed_alias(self):
        style = self._convert([" スギ "])
        values = [r["value"] for r in style["vt-color-rules"]]
        self.assertIn(" スギ ", values)
        self.assertIn("スギ", values)

    def test_absorption_is_reported_as_info(self):
        self._convert(["１２３"])
        self.assertTrue(self._entries(level="INFO"))
        self.assertFalse(self._entries(level="WARN"))

    def test_clean_values_get_no_aliases(self):
        """表記ゆれが無ければ1件も増やさない。"""
        style = self._convert(["スギ", "ヒノキ"])
        self.assertEqual([r["value"] for r in style["vt-color-rules"]],
                         ["スギ", "ヒノキ"])
        self.assertEqual(self._entries(), [])

    def test_duplicates_are_removed(self):
        style = self._convert(["スギ", "スギ", "ヒノキ"])
        self.assertEqual([r["value"] for r in style["vt-color-rules"]],
                         ["スギ", "ヒノキ"])

    def test_first_duplicate_wins(self):
        """MapLibre と同じ「先勝ち」で残す。"""
        cats = [F.Category("A", _fill("1,1,1,255"), "先"),
                F.Category("A", _fill("9,9,9,255"), "後")]
        renderer = F.CategorizedRenderer("cls", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(), self.lrep)
        self.assertEqual(len(style["vt-color-rules"]), 1)
        self.assertEqual(style["vt-color-rules"][0]["label"], "先")

    # --- 吸収OFF ------------------------------------------------------ #
    def test_off_keeps_original_only_and_warns(self):
        opts = ConvertOptions(normalize_values=False)
        style = self._convert(["１２３"], opts)
        self.assertEqual([r["value"] for r in style["vt-color-rules"]], ["１２３"])
        self.assertTrue(self._entries(level="WARN"))

    def test_off_still_removes_duplicates(self):
        opts = ConvertOptions(normalize_values=False)
        style = self._convert(["A", "A"], opts)
        self.assertEqual(len(style["vt-color-rules"]), 1)

    # --- 数値モードとの併用 ------------------------------------------- #
    def test_string_column_with_numeric_looking_values_stays_string(self):
        """全角数字が文字列カテゴリなら、列は文字列型なので文字列ルールのまま。

        step 式は数値属性しか比較できないため、ここで数値化すると
        かえって一致しなくなる。半角の別名で両方に当てる。
        """
        cats = [F.Category("１", _fill(), "壱"), F.Category("２", _fill(), "弐")]
        renderer = F.CategorizedRenderer("code", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(), self.lrep)
        values = [r["value"] for r in style["vt-color-rules"]]
        self.assertTrue(all("num_min" not in r for r in style["vt-color-rules"]))
        self.assertEqual(values, ["１", "1", "２", "2"])

    def test_numeric_column_uses_step_even_with_fullwidth_labels(self):
        """列が数値型（QGISが int を返す）なら step 式になる。"""
        cats = [F.Category(1, _fill(), "壱"), F.Category(2, _fill(), "弐")]
        renderer = F.CategorizedRenderer("code", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(), self.lrep)
        self.assertTrue(all("num_min" in r for r in style["vt-color-rules"]))

    def test_halfwidth_conversion(self):
        from fgstyle_maker.converter.vector import to_halfwidth
        self.assertEqual(to_halfwidth("１２３ＡＢ　ｃ"), "123AB c")

    def test_value_variants(self):
        from fgstyle_maker.converter.vector import value_variants
        self.assertEqual(value_variants("スギ"), [])
        self.assertEqual(value_variants("１２３"), ["123"])
        self.assertEqual(value_variants(" A "), ["A"])


class TestMinLineWidth(unittest.TestCase):
    """細すぎる線幅の引き上げ（QMLがPixel指定でも起きる）。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _line(self, width="0.4", unit="Pixel"):
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="solid"/>'
            '<Option name="line_width" value="{w}"/>'
            '<Option name="line_width_unit" value="{u}"/>'
            '</Option></layer></symbol>'.format(w=width, u=unit)))

    def test_thin_pixel_width_is_raised(self):
        renderer = F.SingleRenderer(self._line("0.4", "Pixel"))
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(min_line_width=1.0),
                                     self.lrep)
        self.assertEqual(style["line-width"], 1.0)
        self.assertTrue(any("細く" in e.message for e in self.lrep.entries))

    def test_thick_width_is_untouched(self):
        renderer = F.SingleRenderer(self._line("2.5", "Pixel"))
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(min_line_width=1.0),
                                     self.lrep)
        self.assertEqual(style["line-width"], 2.5)

    def test_zero_width_stays_zero(self):
        """枠線なし（0）は意図的な指定なので引き上げない。"""
        renderer = F.SingleRenderer(_fill(outline_style="no"))
        style = convert_vector_layer(F.FakeLayer(renderer), "Polygon",
                                     ConvertOptions(min_line_width=1.0),
                                     self.lrep)
        self.assertEqual(style["line-width"], 0.0)

    def test_guard_disabled(self):
        renderer = F.SingleRenderer(self._line("0.4", "Pixel"))
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(min_line_width=0.0),
                                     self.lrep)
        self.assertEqual(style["line-width"], 0.4)

    def test_mm_is_converted_before_guard(self):
        """0.26mm ≒ 0.98px は下限1.0で引き上がる。"""
        renderer = F.SingleRenderer(self._line("0.26", "MM"))
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(min_line_width=1.0),
                                     self.lrep)
        self.assertEqual(style["line-width"], 1.0)

    def test_unit_usage_is_reported(self):
        renderer = F.SingleRenderer(self._line("1.2", "Pixel"))
        convert_vector_layer(F.FakeLayer(renderer), "LineString",
                             ConvertOptions(), self.lrep)
        units = [e for e in self.lrep.entries if e.category == "単位"]
        self.assertTrue(units)
        self.assertIn("Pixel 1.2", units[0].message)


# ===================================================================== #
class TestDashArray(unittest.TestCase):
    """QGISの線種 → line-dasharray（線幅の倍数）。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _line(self, style="solid", width="1.2", unit="Pixel",
              custom="0", dash="", dash_unit="Pixel", offset="0"):
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="{st}"/>'
            '<Option name="line_width" value="{w}"/>'
            '<Option name="line_width_unit" value="{u}"/>'
            '<Option name="use_custom_dash" value="{c}"/>'
            '<Option name="customdash" value="{d}"/>'
            '<Option name="customdash_unit" value="{du}"/>'
            '<Option name="dash_pattern_offset" value="{o}"/>'
            '</Option></layer></symbol>'.format(
                st=style, w=width, u=unit, c=custom, d=dash,
                du=dash_unit, o=offset)))

    def _convert(self, symbol, geom="LineString", opts=None):
        renderer = F.SingleRenderer(symbol)
        return convert_vector_layer(F.FakeLayer(renderer), geom,
                                    opts or ConvertOptions(), self.lrep)

    def test_solid_stays_empty(self):
        style = self._convert(self._line("solid"))
        self.assertEqual(style["line-dasharray"], [])

    def test_dash_line_uses_qt_ratio(self):
        style = self._convert(self._line("dash"))
        self.assertEqual(style["line-dasharray"], [4, 2])

    def test_dot_line(self):
        self.assertEqual(self._convert(self._line("dot"))["line-dasharray"],
                         [1, 2])

    def test_dash_dot_line(self):
        self.assertEqual(
            self._convert(self._line("dash dot"))["line-dasharray"],
            [4, 2, 1, 2])

    def test_dash_dot_dot_line(self):
        self.assertEqual(
            self._convert(self._line("dash dot dot"))["line-dasharray"],
            [4, 2, 1, 2, 1, 2])

    def test_custom_dash_is_divided_by_line_width(self):
        """カスタムダッシュは線幅で割って無次元化される。"""
        style = self._convert(
            self._line(width="2", unit="Pixel", custom="1",
                       dash="6;3", dash_unit="Pixel"))
        self.assertEqual(style["line-dasharray"], [3.0, 1.5])

    def test_custom_dash_in_mm_is_converted_first(self):
        """mm指定のダッシュもpxへ換算してから線幅で割る。"""
        # 線幅 1mm(=3.7795px)、ダッシュ 2mm/1mm → 2.0 / 1.0
        style = self._convert(
            self._line(width="1", unit="MM", custom="1",
                       dash="2;1", dash_unit="MM"))
        self.assertEqual(style["line-dasharray"], [2.0, 1.0])

    def test_dash_offset_is_warned(self):
        self._convert(self._line("dash", offset="1.5"))
        self.assertTrue(any("オフセット" in e.message
                            for e in self.lrep.entries))

    def test_conversion_is_reported(self):
        self._convert(self._line("dash"))
        self.assertTrue(any(e.category == "線種" and "line-dasharray" in e.message
                            for e in self.lrep.entries))

    def test_polygon_outline_dash(self):
        symbol = F.Symbol(ET.fromstring(
            '<symbol type="fill" alpha="1"><layer class="SimpleFill">'
            '<Option type="Map">'
            '<Option name="color" value="1,2,3,255"/>'
            '<Option name="outline_color" value="0,0,0,255"/>'
            '<Option name="outline_style" value="dash"/>'
            '<Option name="outline_width" value="0.5"/>'
            '<Option name="outline_width_unit" value="MM"/>'
            '<Option name="style" value="solid"/>'
            '</Option></layer></symbol>'))
        style = self._convert(symbol, geom="Polygon")
        self.assertEqual(style["line-dasharray"], [4, 2])

    def test_per_category_dash_lands_on_rules(self):
        """区分ごとに線種が違えば rules[].dasharray に載る。"""
        cats = [F.Category(1, self._line("solid"), "実線区分"),
                F.Category(2, self._line("dash"), "破線区分"),
                F.Category(3, self._line("dot"), "点線区分")]
        renderer = F.CategorizedRenderer("code", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(), self.lrep)
        rules = style["vt-color-rules"]
        self.assertEqual(style["line-dasharray"], [])
        self.assertNotIn("dasharray", rules[0])           # 既定と同じなので省略
        self.assertEqual(rules[1]["dasharray"], [4, 2])
        self.assertEqual(rules[2]["dasharray"], [1, 2])

    def test_rule_matching_base_dash_is_omitted(self):
        """レイヤ既定と同じパターンならルールに載せない（冗長を避ける）。"""
        cats = [F.Category(1, self._line("dash"), "A"),
                F.Category(2, self._line("dash"), "B")]
        renderer = F.CategorizedRenderer("code", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(), self.lrep)
        self.assertEqual(style["line-dasharray"], [4, 2])
        self.assertTrue(all("dasharray" not in r
                            for r in style["vt-color-rules"]))


# ===================================================================== #
class TestDashGapLegibility(unittest.TestCase):
    """MapLibre で隙間が細すぎて実線に見える破線への対処。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _line(self, width="1.2", unit="Pixel", dash="4.5;1.5",
              dash_unit="Pixel"):
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="solid"/>'
            '<Option name="line_width" value="{w}"/>'
            '<Option name="line_width_unit" value="{u}"/>'
            '<Option name="use_custom_dash" value="1"/>'
            '<Option name="customdash" value="{d}"/>'
            '<Option name="customdash_unit" value="{du}"/>'
            '<Option name="dash_pattern_offset" value="0"/>'
            '</Option></layer></symbol>'.format(
                w=width, u=unit, d=dash, du=dash_unit)))

    def _convert(self, symbol, opts=None):
        renderer = F.SingleRenderer(symbol)
        return convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                    opts or ConvertOptions(), self.lrep)

    def test_narrow_gap_is_widened_to_minimum(self):
        """4.5px/1.5px @1.2px幅 → 隙間だけ 2px へ広がる。"""
        style = self._convert(self._line())
        width = style["line-width"]
        dash = style["line-dasharray"]
        self.assertAlmostEqual(dash[0] * width, 4.5, places=1)   # 線分は不変
        self.assertAlmostEqual(dash[1] * width, 2.0, places=2)   # 隙間は下限

    def test_widening_is_reported(self):
        self._convert(self._line())
        self.assertTrue(any(e.category == "線種" and "隙間" in e.message
                            for e in self.lrep.entries))

    def test_wide_enough_gap_is_untouched(self):
        """7px/3px @1.2px幅 は下限を満たすのでそのまま。"""
        style = self._convert(self._line(dash="7;3"))
        width = style["line-width"]
        dash = style["line-dasharray"]
        self.assertAlmostEqual(dash[0] * width, 7.0, places=1)
        self.assertAlmostEqual(dash[1] * width, 3.0, places=1)

    def test_zero_minimum_keeps_qgis_ratio(self):
        style = self._convert(self._line(),
                              ConvertOptions(min_dash_gap=0.0))
        self.assertEqual(style["line-dasharray"], [3.75, 1.25])

    def test_min_line_width_does_not_stretch_the_dash(self):
        """最小線幅で 0.4px → 1.0px へ引き上げても破線の実寸は保たれる。"""
        style = self._convert(self._line(width="0.4", dash="4;2"),
                              ConvertOptions(min_line_width=1.0,
                                             min_dash_gap=0.0))
        self.assertEqual(style["line-width"], 1.0)
        # 倍数のままだと [10, 5] → 実寸 10px/5px になってしまう
        dash = style["line-dasharray"]
        self.assertAlmostEqual(dash[0] * 1.0, 4.0, places=2)
        self.assertAlmostEqual(dash[1] * 1.0, 2.0, places=2)

    def test_rescale_is_reported(self):
        self._convert(self._line(width="0.4", dash="4;2"),
                      ConvertOptions(min_line_width=1.0, min_dash_gap=0.0))
        self.assertTrue(any(e.category == "線種" and "組み直し" in e.message
                            for e in self.lrep.entries))

    def test_qt_preset_is_not_rescaled(self):
        """Qt既定パターンは元から線幅の倍数なので線幅変更で組み直さない。"""
        symbol = F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="dash"/>'
            '<Option name="line_width" value="0.4"/>'
            '<Option name="line_width_unit" value="Pixel"/>'
            '<Option name="use_custom_dash" value="0"/>'
            '</Option></layer></symbol>'))
        style = self._convert(symbol, ConvertOptions(min_line_width=1.0,
                                                    min_dash_gap=0.0))
        self.assertEqual(style["line-dasharray"], [4, 2])

    def test_rule_dash_uses_rule_width(self):
        """区分ごとの破線は、その区分の線幅を基準に仕上げられる。"""
        cats = [F.Category(1, self._line(width="1.2", dash="0;0"), "実線"),
                F.Category(2, self._line(width="1.2", dash="4.5;1.5"), "破線")]
        renderer = F.CategorizedRenderer("code", cats)
        style = convert_vector_layer(F.FakeLayer(renderer), "LineString",
                                     ConvertOptions(), self.lrep)
        rule = [r for r in style["vt-color-rules"] if "dasharray" in r][0]
        width = rule.get("width", style["line-width"])
        self.assertAlmostEqual(rule["dasharray"][1] * width, 2.0, places=2)



# ===================================================================== #
class TestLineWidthSource(unittest.TestCase):
    """線幅・単位はシンボルレイヤ側から読む（QgsLineSymbol.widthUnit() は無い）。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _symbol(self, custom="1", dash="4.5;1.5"):
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="solid"/>'
            '<Option name="line_width" value="1.2"/>'
            '<Option name="line_width_unit" value="Pixel"/>'
            '<Option name="use_custom_dash" value="{c}"/>'
            '<Option name="customdash" value="{d}"/>'
            '<Option name="customdash_unit" value="Pixel"/>'
            '<Option name="dash_pattern_offset" value="0"/>'
            '</Option></layer></symbol>'.format(c=custom, d=dash)))

    def test_symbol_has_no_width_unit_getter(self):
        """テスト用フィクスチャが本物のAPIに合っていること（回帰防止）。"""
        self.assertFalse(hasattr(F.Symbol.__mro__[0], "widthUnit"))

    def test_width_is_read_from_symbol_layer(self):
        from fgstyle_maker.converter.symbols import line_width_and_unit
        symbol = self._symbol()
        width, unit = line_width_and_unit(symbol, symbol.symbolLayer(0))
        self.assertEqual(width, 1.2)
        self.assertEqual(unit, "Pixel")

    def test_custom_dash_converts_without_symbol_width_unit(self):
        """symbol.widthUnit() が無くても『換算できませんでした』にならない。"""
        style = convert_vector_layer(
            F.FakeLayer(F.SingleRenderer(self._symbol())), "LineString",
            ConvertOptions(min_dash_gap=0.0), self.lrep)
        self.assertEqual(style["line-width"], 1.2)
        self.assertEqual(style["line-dasharray"], [3.75, 1.25])
        self.assertFalse([e for e in self.lrep.entries
                          if "換算できませんでした" in e.message])

    def test_failure_detail_names_the_missing_piece(self):
        """換算できないときは何が取れなかったかを detail に出す。"""
        symbol = self._symbol(dash="0")          # 要素1つ → 換算不能
        convert_vector_layer(
            F.FakeLayer(F.SingleRenderer(symbol)), "LineString",
            ConvertOptions(), self.lrep)
        bad = [e for e in self.lrep.entries if "換算できませんでした" in e.message]
        self.assertTrue(bad)
        self.assertIn("線幅=", bad[0].detail)



# ===================================================================== #
class TestHairline(unittest.TestCase):
    """QGISの「非常に細い線」（幅0だが描画される）を最小可視幅へ。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _fill(self, outline_width="0", outline_style="solid"):
        return F.Symbol(ET.fromstring(
            '<symbol type="fill" alpha="1"><layer class="SimpleFill">'
            '<Option type="Map">'
            '<Option name="color" value="0,77,0,255"/>'
            '<Option name="outline_color" value="0,0,0,255"/>'
            '<Option name="outline_style" value="{st}"/>'
            '<Option name="outline_width" value="{w}"/>'
            '<Option name="outline_width_unit" value="MM"/>'
            '<Option name="style" value="solid"/>'
            '</Option></layer></symbol>'.format(w=outline_width,
                                                st=outline_style)))

    def _line(self, width="0", style="solid"):
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1"><layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="0,0,0,255"/>'
            '<Option name="line_style" value="{st}"/>'
            '<Option name="line_width" value="{w}"/>'
            '<Option name="line_width_unit" value="MM"/>'
            '</Option></layer></symbol>'.format(w=width, st=style)))

    def _convert(self, symbol, geom, opts=None):
        return convert_vector_layer(F.FakeLayer(F.SingleRenderer(symbol)),
                                    geom, opts or ConvertOptions(), self.lrep)

    def test_polygon_hairline_becomes_min_width(self):
        """ストローク幅=0 かつ 線種=実線 → ヘアライン → 1px。"""
        style = self._convert(self._fill(), "Polygon")
        self.assertEqual(style["line-width"], 1.0)

    def test_no_pen_stays_zero(self):
        """線種=線なし は「枠線なし」なので0のまま。"""
        style = self._convert(self._fill(outline_style="no"), "Polygon")
        self.assertEqual(style["line-width"], 0.0)

    def test_line_hairline_becomes_min_width(self):
        style = self._convert(self._line(), "LineString")
        self.assertEqual(style["line-width"], 1.0)

    def test_hairline_is_reported(self):
        self._convert(self._fill(), "Polygon")
        self.assertTrue(any("非常に細い線" in e.message
                            for e in self.lrep.entries))

    def test_min_line_width_zero_keeps_hairline_as_zero(self):
        """最小線幅を0にすればQGISの指定どおり0のまま。"""
        style = self._convert(self._fill(), "Polygon",
                              ConvertOptions(min_line_width=0.0))
        self.assertEqual(style["line-width"], 0.0)

    def test_per_rule_hairline(self):
        """区分ごとのヘアラインも引き上げる。"""
        cats = [F.Category("A", self._fill(), "A"),
                F.Category("B", self._fill(), "B")]
        style = convert_vector_layer(
            F.FakeLayer(F.CategorizedRenderer("k", cats)), "Polygon",
            ConvertOptions(), self.lrep)
        # 既定も1.0へ上がるので、ルール側に冗長な width は書かれない
        self.assertEqual(style["line-width"], 1.0)
        self.assertTrue(all("width" not in r for r in style["vt-color-rules"]))


# ===================================================================== #
class TestReportDedup(unittest.TestCase):
    """同じ指摘は1行にまとめて件数を出す。"""

    def test_repeated_entries_are_collapsed(self):
        rep, lrep = _report()
        for _ in range(5):
            lrep.approx("線幅", "同じ指摘", "詳細")
        self.assertEqual(len(lrep.entries), 1)
        self.assertEqual(lrep.entries[0].count, 5)
        self.assertEqual(lrep.entries[0].text, "同じ指摘（他4件）")

    def test_different_entries_stay_separate(self):
        rep, lrep = _report()
        lrep.approx("線幅", "A")
        lrep.approx("線幅", "B")
        self.assertEqual(len(lrep.entries), 2)
        self.assertEqual(lrep.entries[0].text, "A")



# ===================================================================== #
class TestCasing(unittest.TestCase):
    """道路記号のような「縁取り＋中心線」の重ね描き。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _line_layer(self, color, width):
        return (
            '<layer class="SimpleLine">'
            '<Option type="Map">'
            '<Option name="line_color" value="{c}"/>'
            '<Option name="line_style" value="solid"/>'
            '<Option name="line_width" value="{w}"/>'
            '<Option name="line_width_unit" value="Pixel"/>'
            '<Option name="use_custom_dash" value="0"/>'
            '</Option></layer>'.format(c=color, w=width))

    def _stacked(self, *pairs):
        """複数の SimpleLine を積んだ線シンボル（定義順＝下から上）。"""
        return F.Symbol(ET.fromstring(
            '<symbol type="line" alpha="1">'
            + "".join(self._line_layer(c, w) for c, w in pairs)
            + '</symbol>'))

    def test_stacked_lines_become_casing_and_center(self):
        """太い線の上に細い線 → 縁取り＋中心線。"""
        symbol = self._stacked(("103,95,128,255", "4.5"),
                               ("106,188,110,255", "3.0"))
        style = convert_vector_layer(F.FakeLayer(F.SingleRenderer(symbol)),
                                     "LineString", ConvertOptions(), self.lrep)
        self.assertEqual(style["line-color"], "#6abc6e")   # 中心線が主役
        self.assertEqual(style["line-width"], 3.0)
        self.assertEqual(style["line-casing-color"], "#675f80")
        self.assertEqual(style["line-casing-width"], 4.5)

    def test_stacked_is_reported(self):
        symbol = self._stacked(("0,0,0,255", "4"), ("255,255,255,255", "2"))
        convert_vector_layer(F.FakeLayer(F.SingleRenderer(symbol)),
                             "LineString", ConvertOptions(), self.lrep)
        self.assertTrue(any("縁取り" in e.message for e in self.lrep.entries))

    def test_single_line_has_no_casing(self):
        symbol = self._stacked(("0,0,0,255", "2"))
        style = convert_vector_layer(F.FakeLayer(F.SingleRenderer(symbol)),
                                     "LineString", ConvertOptions(), self.lrep)
        self.assertNotIn("line-casing-width", style)

    def test_top_wider_is_not_casing(self):
        """上のほうが太いなら縁取り構成ではない（従来どおり先頭のみ）。"""
        symbol = self._stacked(("0,0,0,255", "1"), ("255,0,0,255", "5"))
        style = convert_vector_layer(F.FakeLayer(F.SingleRenderer(symbol)),
                                     "LineString", ConvertOptions(), self.lrep)
        self.assertNotIn("line-casing-width", style)

    def test_per_category_casing(self):
        """区分ごとに縁取りの色・太さが違っても載る。"""
        cats = [F.Category("1", self._stacked(("103,95,128,255", "4.5"),
                                              ("106,188,110,255", "3.0")), "国道"),
                F.Category("5", self._stacked(("215,178,145,255", "1.0")), "その他")]
        style = convert_vector_layer(
            F.FakeLayer(F.CategorizedRenderer("code", cats)), "LineString",
            ConvertOptions(), self.lrep)
        rules = {r["value"]: r for r in style["vt-color-rules"]}
        self.assertEqual(rules["1"]["casing_width"], 4.5)
        self.assertEqual(rules["1"]["casing_color"], "#675f80")
        self.assertEqual(rules["1"]["color"], "#6abc6e")
        self.assertNotIn("casing_width", rules["5"])



# ===================================================================== #
class TestOutlineColorPerRule(unittest.TestCase):
    """面の外周線色を区分ごとに出す（塗りと同じ色で縁取る定義への対応）。"""

    def setUp(self):
        self.rep, self.lrep = _report()

    def _fill(self, color):
        return F.Symbol(ET.fromstring(
            '<symbol type="fill" alpha="1"><layer class="SimpleFill">'
            '<Option type="Map">'
            '<Option name="color" value="{c}"/>'
            '<Option name="outline_color" value="{c}"/>'
            '<Option name="outline_style" value="solid"/>'
            '<Option name="outline_width" value="0"/>'
            '<Option name="outline_width_unit" value="MM"/>'
            '<Option name="style" value="solid"/>'
            '</Option></layer></symbol>'.format(c=color)))

    def test_fgb_uses_an_expression_for_the_outline(self):
        """fgbは fill-outline-color に match 式を直接入れる（従来の仕組み）。"""
        cats = [F.Category("スギ", self._fill("255,75,0,255"), "スギ"),
                F.Category("ヒノキ", self._fill("77,196,255,255"), "ヒノキ")]
        style = convert_vector_layer(
            F.FakeLayer(F.CategorizedRenderer("樹種", cats)), "Polygon",
            ConvertOptions(), self.lrep)
        expr = style["fill-outline-color"]
        self.assertEqual(expr[0], "match")
        self.assertIn("#ff4b00", expr)
        self.assertIn("#4dc4ff", expr)



if __name__ == "__main__":
    unittest.main(verbosity=2)
