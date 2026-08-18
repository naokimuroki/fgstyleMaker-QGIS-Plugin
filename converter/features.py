# -*- coding: utf-8 -*-
"""レンダラ以外の「MapLibreに概念が無い」機能をXMLから検出して報告する。

互換性レポート §7・§9 に挙がっている、変換のしようがない機能群。
レンダラオブジェクトからは辿りにくいものが多いため、`<maplayer>`
（または QML のルート）要素を直接見る。
"""


def _child(element, tag):
    if element is None:
        return None
    if hasattr(element, "firstChildElement"):
        e = element.firstChildElement(tag)
        return None if e.isNull() else e
    return element.find(tag)


def _text(element, tag, default=""):
    e = _child(element, tag)
    if e is None:
        return default
    try:
        return e.text().strip()
    except (AttributeError, TypeError):
        return (e.text or "").strip()


def _attr(element, name, default=""):
    if element is None:
        return default
    if hasattr(element, "attribute"):
        return element.attribute(name) or default
    return element.get(name, default)


def _tag_names(element):
    """直下の子要素タグ名を列挙する。"""
    names = []
    if element is None:
        return names
    if hasattr(element, "firstChildElement"):
        child = element.firstChild()
        while not child.isNull():
            if child.isElement():
                names.append(child.toElement().tagName())
            child = child.nextSibling()
        return names
    return [c.tag for c in element]


def _find_all(element, tag):
    """子孫から tag に一致する要素を全て集める。"""
    out = []
    if element is None:
        return out
    if hasattr(element, "elementsByTagName"):
        nodes = element.elementsByTagName(tag)
        for i in range(nodes.count()):
            el = nodes.at(i).toElement()
            if not el.isNull():
                out.append(el)
        return out
    return list(element.iter(tag))


# ===================================================================== #
_BLEND_MODES = {
    "0": None,          # Normal
    "": None,
}

_DIAGRAM_TAGS = (
    "SingleCategoryDiagramRenderer",
    "LinearlyInterpolatedDiagramRenderer",
    "StackedDiagramRenderer",
    "DiagramLayerSettings",
)


def detect_unsupported(element, report):
    """変換できない機能を洗い出して report に積む。"""
    if element is None:
        return

    _check_blend_modes(element, report)
    _check_diagrams(element, report)
    _check_temporal(element, report)
    _check_paint_effects(element, report)
    _check_geometry_generator(element, report)
    _check_label_extras(element, report)


# --------------------------------------------------------------------- #
def _check_blend_modes(element, report):
    for tag, label in (("blendMode", "レイヤの合成モード"),
                       ("featureBlendMode", "地物単位の合成モード")):
        value = _text(element, tag, "0")
        if value not in ("0", ""):
            report.warn(
                "合成モード",
                "{0}（{1}）は変換できません".format(label, value),
                "MapLibre GL JS はレイヤの合成モード指定を持ちません。"
                "通常合成として描画されます。")


def _check_diagrams(element, report):
    names = set(_tag_names(element))
    found = [t for t in _DIAGRAM_TAGS if t in names]
    if not found:
        return
    # DiagramLayerSettings 単独（enabled=0）は設定の器だけなので除外する
    settings = _child(element, "DiagramLayerSettings")
    renderers = [t for t in found if t != "DiagramLayerSettings"]
    if not renderers:
        if settings is not None and _attr(settings, "showAll") == "" :
            return
        return
    report.warn(
        "ダイアグラム",
        "ダイアグラム（{0}）は変換できません".format(", ".join(renderers)),
        "円グラフ・ヒストグラム等はMapLibreに描画機構がありません。"
        "必要なら集計結果を属性として持たせ、別途表現してください。")


def _check_temporal(element, report):
    node = _child(element, "temporal")
    if node is None:
        return
    if _attr(node, "enabled") in ("1", "true"):
        report.warn(
            "時系列",
            "時系列（Temporal）設定は変換できません",
            "MapLibre側で時刻によるフィルタを行う仕組みがありません。")


def _check_paint_effects(element, report):
    """`<effect>` 要素（ペイントエフェクト）を検出する。"""
    kinds = set()
    for effect in _find_all(element, "effect"):
        if _attr(effect, "enabled") in ("0", ""):
            # ルート effect は器のみ。子の effect が実体
            pass
        for sub in _find_all(effect, "Option"):
            name = _attr(sub, "name")
            if name == "enabled" and _attr(sub, "value") == "1":
                pass
        etype = _attr(effect, "type")
        if etype and etype not in ("effectStack",):
            kinds.add(etype)

    if not kinds:
        return

    supported_note = {
        "outerGlow": "外側グロー", "innerGlow": "内側グロー",
        "drawSource": None, "blur": "ぼかし",
        "dropShadow": "ドロップシャドウ", "innerShadow": "内側シャドウ",
        "colorize": "色調変換", "transform": "変形",
    }
    labels = []
    for k in sorted(kinds):
        label = supported_note.get(k, k)
        if label:
            labels.append(label)
    if not labels:
        return
    report.warn(
        "ペイントエフェクト",
        "ペイントエフェクト（{0}）は変換できません".format("、".join(labels)),
        "MapLibre GL JS に相当する描画効果がありません。")


def _check_geometry_generator(element, report):
    for layer in _find_all(element, "layer"):
        if _attr(layer, "class") == "GeometryGenerator":
            report.warn(
                "ジオメトリジェネレータ",
                "ジオメトリジェネレータは変換できません",
                "描画時に形状を生成する仕組みはMapLibreにありません。"
                "QGIS側でジオメトリを実体化（バッファ等を実データ化）してから"
                "出力してください。")
            return


def _check_label_extras(element, report):
    labeling = _child(element, "labeling")
    if labeling is None:
        return

    for node in _find_all(labeling, "callout"):
        if _attr(node, "enabled") in ("1", "true"):
            report.warn(
                "引き出し線",
                "ラベルの引き出し線（Callout）は変換できません",
                "MapLibreに引き出し線の機構がありません。線分を別レイヤとして"
                "生成する必要があります。")
            break

    for node in _find_all(labeling, "text-mask"):
        if _attr(node, "maskEnabled") in ("1", "true"):
            report.warn(
                "ラベルマスク",
                "ラベルマスクは変換できません",
                "MapLibreにマスク機構がありません。")
            break
