# -*- coding: utf-8 -*-
"""変換パラメータ。"""


class ConvertOptions(object):
    """変換時の挙動を制御する設定値。

    dpi
        QGISの mm / pt / inch 指定を CSS ピクセルへ換算するときの解像度。
        MapLibre GL JS は CSS ピクセル基準なので 96 が標準。
    reference_latitude
        縮尺分母 ↔ WebMercatorズームレベルの換算に使う基準緯度（度）。
        Web メルカトルは高緯度ほど引き伸ばされるため、緯度によって
        同じズームでも縮尺が変わる。日本の森林域なら 35〜43 程度。
    reference_zoom
        マップ単位（メートル）指定の線幅・記号サイズをピクセルへ
        近似換算するときの基準ズーム。
    round_zoom
        True なら minzoom/maxzoom を整数に丸める（minzoomは切り上げ、
        maxzoomは切り捨て）。False なら小数2桁で保持する。
    convert_scale_visibility
        QGISの縮尺依存表示を minzoom/maxzoom へ変換するか。
    convert_labeling
        ラベル設定を変換するか。
    default_color
        どのルールにも該当しない地物に使う既定色（`#rrggbb`）。
        QGISは「該当なし」を描画しないが、MapLibre の match / step 式は
        必ず既定値へフォールバックするため、消すことはできない。
        そこで**既定色で描く**ことを原則とし、その色をここで決める。
        分類レンダラに「すべての他の値」カテゴリがある場合は、
        そちらのQGIS側の色が優先される。
    emit_rule_labels
        ルールに凡例表示名 `label` を付けるか。QGISのルールベース／分類は
        「判定値」と「凡例ラベル」が別物なことが多い（例: 判定は ser = 619、
        凡例は "K21_vas_ap"）。`.fgstyle` v1 に label キーは無いが、未知キーは
        無視されるため付けても安全。ForestGeo Studio 側はルール表の
        「凡例表示名」列として扱い、そのまま凡例に反映する。
    numeric_strategy
        分類フィールドが数値型のときの出力方法。**'auto' 固定**。
        num_min/num_max による step 式で出力する。本体側の入力式が
        to-number / to-string で型を揃えるため、FlatGeobuf・MVT の
        属性が数値でも文字列でも同じ結果になる。
        （以前あった 'string' / 'expression' は、利用者が選ぶ意味が
          無くなったため廃止した。）
    close_numeric_gaps
        'auto' で step 式にしたとき、区分と区分のあいだ（例: コード2の次が
        コード4なら 3）に不可視のダミー区分を挿入して、区分に無い値が
        直前の色で塗られるのを防ぐか。凡例に余分な行が増えるため既定はOFF。
    normalize_values
        判定値の表記ゆれをプラグイン側で吸収するか。
        全角英数字・全角空白・前後の空白を含む判定値があれば、
        半角化／トリムした**別名ルール**を同じ色で自動追加し、
        データ側がどちらの表記でも一致するようにする。
        表記ゆれが無ければ何も追加しない（＝通常のデータでは無害）。
        重複した判定値は MapLibre が先勝ちで評価するため、
        後続の無効なルールを取り除く（この処理は常に行う）。
    min_line_width
        線幅・枠幅がこの値（px）を下回る場合に引き上げる下限。
        QGISはサブピクセル幅の線をヘアライン（実質1px）として描くのに対し、
        MapLibre はそのまま細く描くため「細すぎて見えない」が起きる。
        0 にすると引き上げない。
    min_dash_gap
        破線の「隙間」がこの値（px）を下回る場合に広げる下限。
        MapLibre は線の縁（破線の切れ目も含む）を必ずアンチエイリアスする
        ため、隙間が 2px 程度を下回ると左右のにじみが重なって実線に見える。
        QGIS（Qt）は切れ目を鋭く描くので、同じ数値でもWEBの方が
        つながって見える。線分（ダッシュ）の長さは変えずに隙間だけを
        広げるので、区分ごとの「短い破線／長い破線」の差は保たれる。
        0 にすると広げない（QGISの比率をそのまま出す）。
    allow_expressions
        MapLibre式・rgba色を出力してよいか。**True 固定**。
        `.fgstyle` のスカラーキーは `_build_html()` が MapLibre の
        paint / layout へ素通しするため、値に式や rgba() を入れれば
        そのまま反映される。これにより次が可能になる:
          * QGIS式（データ定義プロパティ・複雑なルール条件）の再現
          * マップ単位指定の線幅・記号サイズをズーム依存の実寸で再現
          * カテゴリごとの円の半径・縁取り色などの出し分け
          * 点シンボルの不透明度（rgba色として畳み込む）
        本体側は式値をUIプリセット／適用から保護するので、
        利用者が意識する必要はない。
    max_rules
        1レイヤあたりのルール数の上限（超過分は切り捨てて警告）。
        地質図など数百区分のスタイルがあるため既定を大きめに取る。
    """

    def __init__(self,
                 dpi=96.0,
                 reference_latitude=35.0,
                 reference_zoom=16.0,
                 round_zoom=False,
                 convert_scale_visibility=True,
                 convert_labeling=True,
                 default_color="#cccccc",
                 emit_rule_labels=True,
                 close_numeric_gaps=False,
                 normalize_values=True,
                 min_line_width=1.0,
                 min_dash_gap=2.0,
                 max_rules=1000):
        self.dpi = float(dpi)
        self.reference_latitude = float(reference_latitude)
        self.reference_zoom = float(reference_zoom)
        self.round_zoom = bool(round_zoom)
        self.convert_scale_visibility = bool(convert_scale_visibility)
        self.convert_labeling = bool(convert_labeling)
        self.default_color = str(default_color or "#cccccc")
        self.emit_rule_labels = bool(emit_rule_labels)
        # 以下は固定値（UIから外した。説明はクラスのdocstring参照）
        self.numeric_strategy = "auto"
        self.allow_expressions = True
        self.categorized_fallback_as_default = True
        self.close_numeric_gaps = bool(close_numeric_gaps)
        self.normalize_values = bool(normalize_values)
        self.min_line_width = float(min_line_width)
        self.min_dash_gap = float(min_dash_gap)
        self.max_rules = int(max_rules)

    def to_dict(self):
        return dict(self.__dict__)
