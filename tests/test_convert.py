# -*- coding: utf-8 -*-
"""converter の単体テスト（QGIS不要）。

実行:
    python3 -m fgstyle_maker.tests.test_convert  <sample.qml> [...]
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from fgstyle_maker.tests import qgis_stub          # noqa: E402
qgis_stub.install()

from PyQt5.QtGui import QColor                     # noqa: E402
from PyQt5.QtXml import QDomDocument               # noqa: E402

from fgstyle_maker.converter.expressions import (  # noqa: E402
    parse_condition, plain_field_name)
from fgstyle_maker.converter.options import ConvertOptions          # noqa: E402
from fgstyle_maker.converter.report import ConversionReport, Level  # noqa: E402
from fgstyle_maker.converter.units import (                        # noqa: E402
    to_pixels, scale_to_zoom, scale_range_to_zoom_range, color_to_hex)
from fgstyle_maker.converter.vector import convert_vector_layer     # noqa: E402
from fgstyle_maker.converter.core import build_payload, safe_filename  # noqa: E402
from fgstyle_maker.tests import qml_fixture        # noqa: E402


SAMPLE_QMLS = [p for p in sys.argv[1:] if p.lower().endswith(".qml")]


def _report():
    rep = ConversionReport()
    return rep, rep.layer("テスト")


# ===================================================================== #
class TestUnits(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def test_mm_to_pixels(self):
        # 1mm @96dpi = 96/25.4 = 3.7795px
        self.assertAlmostEqual(
            to_pixels(1.0, "MM", self.opts, self.lrep), 96 / 25.4, places=4)

    def test_point_to_pixels(self):
        # 12pt @96dpi = 16px
        self.assertAlmostEqual(
            to_pixels(12.0, "Point", self.opts, self.lrep), 16.0, places=6)

    def test_pixel_passthrough(self):
        self.assertEqual(to_pixels(1.2, "Pixel", self.opts, self.lrep), 1.2)

    def test_mapunit_is_approximated_and_reported(self):
        px = to_pixels(10.0, "MapUnit", self.opts, self.lrep)
        self.assertGreater(px, 0)
        self.assertTrue(any(e.level == Level.APPROX for e in self.lrep.entries))

    def test_scale_to_zoom_equator(self):
        # 赤道・96dpi では z0 の縮尺分母 ≒ 591,657,527
        opts = ConvertOptions(reference_latitude=0.0, dpi=96.0)
        self.assertAlmostEqual(scale_to_zoom(591657527.591555, opts), 0.0,
                               places=5)
        self.assertAlmostEqual(scale_to_zoom(591657527.591555 / 2, opts), 1.0,
                               places=5)

    def test_scale_range_orders_and_clamps(self):
        opts = ConvertOptions(reference_latitude=0.0)
        # 1:100000（引き）〜 1:1000（寄り）
        zmin, zmax = scale_range_to_zoom_range(100000, 1000, opts)
        self.assertLess(zmin, zmax)
        self.assertGreaterEqual(zmin, 0.0)
        self.assertLessEqual(zmax, 24.0)

    def test_scale_zero_means_unlimited(self):
        opts = ConvertOptions()
        zmin, zmax = scale_range_to_zoom_range(0, 0, opts)
        self.assertEqual((zmin, zmax), (0.0, 24.0))

    def test_color_to_hex_drops_alpha(self):
        self.assertEqual(color_to_hex(QColor(255, 0, 0, 128)), "#ff0000")


# ===================================================================== #
class TestExpressions(unittest.TestCase):

    def test_bare_field_numeric_equality(self):
        c = parse_condition("ser = 619")
        self.assertEqual((c.kind, c.field, c.values), ("value", "ser", ["619"]))
        self.assertTrue(c.numeric_literal)

    def test_underscore_field(self):
        c = parse_condition("Major_Code = 1")
        self.assertEqual((c.field, c.values), ("Major_Code", ["1"]))

    def test_quoted_japanese_field_string(self):
        c = parse_condition('"樹種" = \'スギ\'')
        self.assertEqual((c.kind, c.field, c.values), ("value", "樹種", ["スギ"]))
        self.assertFalse(c.numeric_literal)

    def test_is_null_becomes_empty_string(self):
        c = parse_condition('"樹種" IS NULL')
        self.assertEqual(c.values, [""])

    def test_in_list(self):
        c = parse_condition('"区分" IN (\'A\', \'B\', \'C\')')
        self.assertEqual(c.values, ["A", "B", "C"])

    def test_range(self):
        c = parse_condition('"林齢" >= 10 AND "林齢" < 20')
        self.assertEqual((c.kind, c.num_min, c.num_max), ("range", 10.0, 20.0))

    def test_range_with_mismatched_fields_is_rejected(self):
        self.assertIsNone(parse_condition('"a" >= 1 AND "b" < 2'))

    def test_unsupported_expression(self):
        self.assertIsNone(parse_condition('length("name") > 3'))

    def test_plain_field_name(self):
        self.assertEqual(plain_field_name('"樹種"'), "樹種")
        self.assertEqual(plain_field_name("ser"), "ser")
        self.assertIsNone(plain_field_name('concat("a","b")'))


# ===================================================================== #
def _fill_symbol(color="10,20,30,255", outline="200,200,200,255",
                 outline_style="solid", outline_width="0.26",
                 outline_unit="MM", alpha="1"):
    import xml.etree.ElementTree as ET
    xml = (
        '<symbol type="fill" alpha="{alpha}">'
        '<layer class="SimpleFill">'
        '<Option type="Map">'
        '<Option name="color" value="{color}"/>'
        '<Option name="outline_color" value="{outline}"/>'
        '<Option name="outline_style" value="{ostyle}"/>'
        '<Option name="outline_width" value="{owidth}"/>'
        '<Option name="outline_width_unit" value="{ounit}"/>'
        '<Option name="style" value="solid"/>'
        '</Option></layer></symbol>'
    ).format(alpha=alpha, color=color, outline=outline,
             ostyle=outline_style, owidth=outline_width, ounit=outline_unit)
    return qml_fixture.Symbol(ET.fromstring(xml))


class TestCategorized(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def test_categories_become_string_rules(self):
        cats = [
            qml_fixture.Category("スギ", _fill_symbol("45,138,78,255"), "スギ"),
            qml_fixture.Category("ヒノキ", _fill_symbol("124,179,66,255"), "ヒノキ"),
        ]
        renderer = qml_fixture.CategorizedRenderer("樹種", cats)
        layer = qml_fixture.FakeLayer(renderer)
        style = convert_vector_layer(layer, "Polygon", self.opts, self.lrep)

        self.assertTrue(style["vt-color-rule-enabled"])
        self.assertEqual(style["vt-color-rule-field"], "樹種")
        self.assertEqual([r["value"] for r in style["vt-color-rules"]],
                         ["スギ", "ヒノキ"])
        self.assertEqual(style["vt-color-rules"][0]["color"], "#2d8a4e")

    def test_null_fallback_category_becomes_default_color(self):
        cats = [
            qml_fixture.Category("スギ", _fill_symbol("45,138,78,255"), "スギ"),
            qml_fixture.Category(None, _fill_symbol("204,204,204,255"), ""),
        ]
        renderer = qml_fixture.CategorizedRenderer("樹種", cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                     "Polygon", self.opts, self.lrep)
        self.assertEqual(len(style["vt-color-rules"]), 1)
        self.assertEqual(style["fill-color"], "#cccccc")

    def test_numeric_categories_become_step_rules_by_default(self):
        """数値カテゴリは既定で step 式（本体パッチ不要）になる。"""
        cats = [qml_fixture.Category(619, _fill_symbol("1,2,3,255"), "A"),
                qml_fixture.Category(8, _fill_symbol("4,5,6,255"), "B")]
        renderer = qml_fixture.CategorizedRenderer("ser", cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                                     self.opts, self.lrep)
        rules = style["vt-color-rules"]
        self.assertTrue(all("num_min" in r for r in rules))
        self.assertEqual([r["num_min"] for r in rules], [8, 619])  # 昇順
        self.assertTrue(all(r["value"] == "" for r in rules))
        self.assertNotIn("to-string", str(self.lrep.patches))

    def test_numeric_categories_are_reported(self):
        cats = [qml_fixture.Category(619, _fill_symbol(), "K21_vas_ap")]
        renderer = qml_fixture.CategorizedRenderer("ser", cats)
        opts = ConvertOptions()
        convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                             opts, self.lrep)
        self.assertTrue(any("数値" in e.message for e in self.lrep.entries))

    def test_label_is_emitted_when_different_from_value(self):
        cats = [qml_fixture.Category(619, _fill_symbol(), "K21_vas_ap")]
        renderer = qml_fixture.CategorizedRenderer("ser", cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                                     self.opts, self.lrep)
        self.assertEqual(style["vt-color-rules"][0]["label"], "K21_vas_ap")

    def test_label_survives_numeric_conversion(self):
        """step 式へ変換しても凡例名は保持される。"""
        cats = [qml_fixture.Category(1, _fill_symbol(), "境界"),
                qml_fixture.Category(2, _fill_symbol(), "断層")]
        renderer = qml_fixture.CategorizedRenderer("code", cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                                     self.opts, self.lrep)
        self.assertEqual([r["label"] for r in style["vt-color-rules"]],
                         ["境界", "断層"])

    def test_label_omitted_when_option_off(self):
        opts = ConvertOptions(emit_rule_labels=False)
        cats = [qml_fixture.Category(619, _fill_symbol(), "K21_vas_ap")]
        renderer = qml_fixture.CategorizedRenderer("ser", cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                                     opts, self.lrep)
        self.assertNotIn("label", style["vt-color-rules"][0])

    def test_expression_class_attribute_is_rejected(self):
        cats = [qml_fixture.Category("A", _fill_symbol(), "A")]
        renderer = qml_fixture.CategorizedRenderer('concat("a","b")', cats)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                                     self.opts, self.lrep)
        self.assertFalse(style["vt-color-rule-enabled"])


class TestGraduated(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def _renderer(self):
        ranges = [
            qml_fixture.Range(0, 10, _fill_symbol("232,245,233,255"), "0 - 10"),
            qml_fixture.Range(10, 20, _fill_symbol("165,214,167,255"), "10 - 20"),
            qml_fixture.Range(20, 40, _fill_symbol("76,175,80,255"), "20 - 40"),
        ]
        return qml_fixture.GraduatedRenderer("林齢", ranges)

    def test_ranges_become_numeric_rules(self):
        style = convert_vector_layer(qml_fixture.FakeLayer(self._renderer()),
                                     "Polygon", self.opts, self.lrep)
        rules = style["vt-color-rules"]
        self.assertEqual([r["num_min"] for r in rules], [0, 10, 20])
        self.assertEqual([r["num_max"] for r in rules], [10, 20, 40])
        self.assertTrue(all(r["value"] == "" for r in rules))

    def test_contiguous_ranges_report_no_gap(self):
        convert_vector_layer(qml_fixture.FakeLayer(self._renderer()),
                             "Polygon", self.opts, self.lrep)
        self.assertFalse(any("隙間" in e.message for e in self.lrep.entries))

    def test_gap_is_reported(self):
        ranges = [
            qml_fixture.Range(0, 10, _fill_symbol(), "a"),
            qml_fixture.Range(20, 30, _fill_symbol(), "b"),
        ]
        renderer = qml_fixture.GraduatedRenderer("林齢", ranges)
        convert_vector_layer(qml_fixture.FakeLayer(renderer), "Polygon",
                             self.opts, self.lrep)
        self.assertTrue(any("隙間" in e.message for e in self.lrep.entries))

    def test_out_of_range_uses_the_default_color(self):
        """区分外は消さず、設定の既定色で描く。"""
        opts = ConvertOptions(default_color="#abcdef")
        style = convert_vector_layer(qml_fixture.FakeLayer(self._renderer()),
                                     "Polygon", opts, self.lrep)
        self.assertEqual(style["fill-color"], "#abcdef")
        # 不透明度・線幅は0にしない（消さないので塗り戻しも不要）
        self.assertNotEqual(style["fill-opacity"], 0.0)
        self.assertTrue(any("既定色" in e.message for e in self.lrep.entries))

    def test_default_color_applies_to_points_too(self):
        """点も同じ扱い（以前は「非表示にできない」と警告していた）。"""
        opts = ConvertOptions(default_color="#123456")
        ranges = [qml_fixture.Range(0, 10, _fill_symbol(), "a")]
        renderer = qml_fixture.GraduatedRenderer("h", ranges)
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer), "Point",
                                     opts, self.lrep)
        self.assertEqual(style["circle-color"], "#123456")



class TestSymbolExtraction(unittest.TestCase):

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def test_outline_style_no_gives_zero_width(self):
        renderer = qml_fixture.SingleRenderer(
            _fill_symbol(outline_style="no", outline_width="0.26"))
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                     "Polygon", self.opts, self.lrep)
        self.assertEqual(style["line-width"], 0.0)

    def test_symbol_alpha_becomes_fill_opacity(self):
        renderer = qml_fixture.SingleRenderer(_fill_symbol(alpha="0.5"))
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                     "Polygon", self.opts, self.lrep)
        self.assertAlmostEqual(style["fill-opacity"], 0.5, places=3)

    def test_color_alpha_multiplies_into_opacity(self):
        renderer = qml_fixture.SingleRenderer(
            _fill_symbol(color="10,20,30,128", alpha="1"))
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                     "Polygon", self.opts, self.lrep)
        self.assertAlmostEqual(style["fill-opacity"], 128 / 255.0, places=3)

    def test_layer_opacity_is_folded_in(self):
        renderer = qml_fixture.SingleRenderer(_fill_symbol(alpha="1"))
        layer = qml_fixture.FakeLayer(renderer, opacity=0.5)
        style = convert_vector_layer(layer, "Polygon", self.opts, self.lrep)
        self.assertAlmostEqual(style["fill-opacity"], 0.5, places=3)


class TestSpecCompliance(unittest.TestCase):
    """.fgstyle 定義書 v1 との整合。"""

    def setUp(self):
        self.opts = ConvertOptions()
        self.rep, self.lrep = _report()

    def test_payload_shape(self):
        renderer = qml_fixture.SingleRenderer(_fill_symbol())
        style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                     "Polygon", self.opts, self.lrep)
        payload = build_payload("林小班", style)
        self.assertEqual(payload["_format"], "forestgeostudio-layer-style")
        self.assertEqual(payload["_version"], 1)
        self.assertEqual(payload["_layer_name"], "林小班")
        self.assertEqual(payload["geom"], "Polygon")
        self.assertIs(payload["style"], style)
        json.dumps(payload, ensure_ascii=False)   # 直列化できること

    def test_geom_values_are_known(self):
        for geom in ("Point", "LineString", "Polygon"):
            renderer = qml_fixture.SingleRenderer(_fill_symbol())
            style = convert_vector_layer(qml_fixture.FakeLayer(renderer),
                                         geom, self.opts, self.lrep)
            self.assertEqual(style["geom"], geom)

    def test_zoom_keys_within_range(self):
        renderer = qml_fixture.SingleRenderer(_fill_symbol())
        layer = qml_fixture.FakeLayer(renderer, scale=(100000, 1000))
        style = convert_vector_layer(layer, "Polygon", self.opts, self.lrep)
        for key in ("minzoom", "maxzoom", "text-minzoom", "text-maxzoom"):
            self.assertGreaterEqual(style[key], 0)
            self.assertLessEqual(style[key], 24)

    def test_safe_filename_matches_host_rules(self):
        self.assertEqual(safe_filename('林小班:2024/A'), "林小班_2024_A.fgstyle")
        used = set()
        self.assertEqual(safe_filename("A", used), "A.fgstyle")
        self.assertEqual(safe_filename("A", used), "A_2.fgstyle")


class TestReaderXmlHelpers(unittest.TestCase):
    """reader の XML 組み替え（QGIS本体不要の部分）。"""

    def _doc(self, xml):
        doc = QDomDocument()
        doc.setContent(xml)
        return doc

    def test_style_document_moves_children_and_attributes(self):
        from fgstyle_maker.converter import reader
        doc = self._doc(
            '<maplayer type="vector" hasScaleBasedVisibilityFlag="1" '
            'minScale="50000" maxScale="1000">'
            '<layername>テスト</layername>'
            '<renderer-v2 type="singleSymbol"/>'
            '</maplayer>')
        out = reader._style_document_from(doc.documentElement())
        root = out.documentElement()
        self.assertEqual(root.tagName(), "qgis")
        self.assertEqual(root.attribute("minScale"), "50000")
        self.assertEqual(root.attribute("hasScaleBasedVisibilityFlag"), "1")
        self.assertFalse(root.firstChildElement("renderer-v2").isNull())

    def test_detect_geometry_cascade(self):
        from fgstyle_maker.converter import reader
        cases = [
            ('<maplayer><layerGeometryType>2</layerGeometryType></maplayer>',
             "Polygon"),
            ('<maplayer geometry="Line"/>', "LineString"),
            ('<maplayer><renderer-v2><symbols><symbol type="marker"/>'
             '</symbols></renderer-v2></maplayer>', "Point"),
            ('<maplayer/>', None),
        ]
        for xml, expected in cases:
            el = self._doc(xml).documentElement()
            self.assertEqual(reader._detect_geometry(el), expected, xml)

    def test_field_names_are_collected(self):
        from fgstyle_maker.converter import reader
        el = self._doc(
            '<maplayer><fieldConfiguration>'
            '<field name="ser"/><field name="樹種"/>'
            '</fieldConfiguration></maplayer>').documentElement()
        self.assertEqual(reader._field_names(el), ["ser", "樹種"])


# ===================================================================== #
class TestRealQml(unittest.TestCase):
    """実サンプル（コマンドライン引数で渡されたQML）での通し検証。"""

    def setUp(self):
        if not SAMPLE_QMLS:
            self.skipTest("QMLサンプルが指定されていません")
        self.opts = ConvertOptions()

    def test_samples_convert_without_error(self):
        for path in SAMPLE_QMLS:
            rep = ConversionReport()
            lrep = rep.layer(os.path.basename(path))
            layer, geom = qml_fixture.load_qml(path)
            style = convert_vector_layer(layer, geom, self.opts, lrep)

            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(rep.count(Level.ERROR), 0, rep.to_text())
                self.assertEqual(style["geom"], geom)
                self.assertTrue(style["vt-color-rule-enabled"])
                self.assertTrue(style["vt-color-rules"])
                # 定義書 v1 の必須キーがそろっていること
                for rule in style["vt-color-rules"]:
                    self.assertIn("color", rule)
                    self.assertTrue(rule["color"].startswith("#"))
                json.dumps(build_payload("t", style), ensure_ascii=False)


# ===================================================================== #
if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
