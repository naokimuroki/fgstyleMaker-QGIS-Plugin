# `.fgstyle` スタイル設定ファイル 定義書

**対象**: ForestGeo Studio（Qgis2MapLibrePro）レイヤスタイル設定ファイル
**フォーマット識別子**: `forestgeostudio-layer-style`
**バージョン**: 1
**準拠実装**: `dialog.py`（`_save_style_to_file` / `_load_style_from_file` / `_default_style` / `_apply_style_to_layer` / `_on_layer_selected` / `_build_color_expr` / `_build_value_expr` / `_build_legend` / `_build_vector_tile_layers` / `_build_html`）
**最終更新**: 2026-08-17

---

## 目次

1. [ファイル概要](#1-ファイル概要)
2. [トップレベル構造](#2-トップレベル構造)
3. [`geom`（スタイル種別ディスクリミネータ）](#3-geomスタイル種別ディスクリミネータ)
4. [共通キー](#4-共通キー)
5. [点レイヤ（Point）](#5-点レイヤpoint)
6. [線レイヤ（LineString）](#6-線レイヤlinestring) / [破線](#61-破線-line-dasharray)
7. [面レイヤ（Polygon）](#7-面レイヤpolygon)
8. [ラベル（点・線・面 共通）](#8-ラベル点線面-共通)
9. [ベクトルタイル（VectorTile）](#9-ベクトルタイルvectortile)
10. [ラスタ（Raster / Raster(Tile)）](#10-ラスタraster--rastertile)
11. [属性値色分けルール `vt-color-rules`](#11-属性値色分けルール-vt-color-rules)
12. [凡例の生成規則](#12-凡例の生成規則)
13. [読み込み時の挙動と互換性](#13-読み込み時の挙動と互換性)
14. [実例 JSON サンプル集](#14-実例-json-サンプル集)
15. [MapLibre式による拡張](#15-maplibre式による拡張)
16. [付録A: キー一覧（アルファベット順・逆引き）](#付録a-キー一覧アルファベット順逆引き)
17. [付録B: 既知の注意点・落とし穴](#付録b-既知の注意点落とし穴)

---

## 1. ファイル概要

| 項目 | 内容 |
| --- | --- |
| 拡張子 | `.fgstyle`（実体は JSON テキスト） |
| 文字コード | UTF-8（BOM なし）。`ensure_ascii=False` で日本語はそのまま出力される |
| 整形 | `indent=2` の pretty print |
| 粒度 | **1ファイル = 1レイヤ分**のスタイル設定 |
| 読込時に受理する拡張子 | `.fgstyle` / `.json` / 任意（フィルタ「すべてのファイル」） |
| 保存時の既定ファイル名 | QGIS レイヤ名の禁止文字（`<>:"/\|?*` と制御文字）を `_` に置換したもの + `.fgstyle` |

### 保存の流れ

1. レイヤ一覧で対象レイヤを選択して「スタイル保存」を実行する。
2. 保存直前に `_apply_style_to_layer()` が内部で呼ばれる。
   → **「このレイヤにスタイルを適用」を押し忘れていても、画面に見えている設定がそのまま保存される。**
3. ラッパー（`_format` / `_version` / `_layer_name` / `geom` / `style`）を付けて JSON 出力する。

### 読込の流れ

1. レイヤ一覧で適用先レイヤを選択して「スタイル読込」を実行する。
2. ファイルの `style` が現在のスタイル辞書へ **マージ**（`dict.update`）される。
3. UI に**プリセット**されるだけで、確定はしない。
   → **ユーザが「このレイヤにスタイルを適用」を押して初めて確定する。**

---

## 2. トップレベル構造

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "林小班ポリゴン",
  "geom": "Polygon",
  "style": { }
}
```

| キー | 型 | 出力 | 読込時の扱い | 説明 |
| --- | --- | --- | --- | --- |
| `_format` | string | 必須 | 参照されない | 固定値 `"forestgeostudio-layer-style"`（`STYLE_FILE_FORMAT`）。他システムとの識別用 |
| `_version` | integer | 必須 | 参照されない | 仕様バージョン。現行 `1`（`STYLE_FILE_VERSION`） |
| `_layer_name` | string | 必須 | 参照されない | 保存元 QGIS レイヤ名。人が見て判別するための情報 |
| `geom` | string | 必須 | 参照されない（`style.geom` を見る） | `style.geom` の複製。可読性のための冗長キー |
| `style` | object | **必須** | **本体** | スタイル設定の実体。以降の章はすべて `style` 直下のキーを指す |

> **注**: `_` で始まるキーはメタ情報であり、`style` の中身ではない。将来キーを追加する場合も `_` プレフィックスを予約する。

### 読み込みで受理される3形態

`_load_style_from_file()` は以下の順で判定する。

| # | 条件 | 採用される内容 |
| --- | --- | --- |
| 1 | トップレベルが object かつ `style` が object | `payload["style"]` |
| 2 | トップレベルが object かつ `geom` が真値 | **payload 全体**を style とみなす（ラッパーなしの素の style 辞書） |
| 3 | 上記以外 | エラー：「このファイルは有効なスタイル設定ではないようです。」 |

形態2があるため、`{"geom": "Point", "circle-color": "#ff0000"}` のような最小 JSON も直接読み込める。手書きで部分的なプリセットを作る場合に有用。

---

## 3. `geom`（スタイル種別ディスクリミネータ）

`style.geom` は **どのキー群が有効かを決める唯一のキー**である。

| `geom` の値 | 対象 | 有効なキー群 |
| --- | --- | --- |
| `"Point"` | 点ベクタ（FlatGeobuf 出力） | [5章](#5-点レイヤpoint) + [8章](#8-ラベル点線面-共通) + [11章](#11-属性値色分けルール-vt-color-rules) |
| `"LineString"` | 線ベクタ（FlatGeobuf 出力） | [6章](#6-線レイヤlinestring) + [8章](#8-ラベル点線面-共通) + [11章](#11-属性値色分けルール-vt-color-rules) |
| `"Polygon"` | 面ベクタ（FlatGeobuf 出力） | [7章](#7-面レイヤpolygon) + [8章](#8-ラベル点線面-共通) + [11章](#11-属性値色分けルール-vt-color-rules) |
| `"VectorTile"` | ベクトルタイル（MVT/PBF） | [9章](#9-ベクトルタイルvectortile) + [11章](#11-属性値色分けルール-vt-color-rules) |
| `"Raster"` | 画像ラスタ（ファイル） | [10章](#10-ラスタraster--rastertile) |
| `"Raster(Tile)"` | ラスタタイル（XYZ / WMS） | [10章](#10-ラスタraster--rastertile) |
| `"Vector"` | ジオメトリ判定不能なベクタ | `geom` のみ（実質スタイルなし） |
| `"Unknown"` | 未対応レイヤ型 | `geom` のみ |

### 種別不一致時の挙動

読込時、**ファイルの `geom` と選択中レイヤの `geom` が異なる**場合：

1. 確認ダイアログ「選択中レイヤの種別（X）と、ファイルのスタイル種別（Y）が異なります。種別が一致する項目のみがプリセットされます。続行しますか？」を表示する。
2. 「はい」を選ぶとマージは実行されるが、**マージ後に `geom` は選択中レイヤの値へ強制的に戻される**。
3. 結果として、種別が違う側のキー（例: Polygon レイヤに Point 用 `circle-color`）は辞書に残るが、HTML 生成時には参照されない。

> **設計意図**: 種別をまたいだ誤適用でレイヤが消えることを防ぎつつ、共通キー（`vt-color-rule-*`、ラベル系、`minzoom`/`maxzoom`）だけは流用できるようにしている。

---

## 4. 共通キー

| キー | 型 | 既定値 | 範囲 | 適用対象 | 対応UI |
| --- | --- | --- | --- | --- | --- |
| `geom` | string | — | [3章](#3-geomスタイル種別ディスクリミネータ)参照 | 全種別 | （自動判定） |
| `minzoom` | number | `0` | 0–24 | Point / LineString / Polygon / Raster | `spinPointMinZoom` 等 |
| `maxzoom` | number | `24` | 0–24 | Point / LineString / Polygon / Raster | `spinPointMaxZoom` 等 |

- `minzoom` / `maxzoom` は MapLibre の**レイヤ表示ズーム範囲**にそのまま渡される（float 化される）。
- VectorTile では `minzoom` / `maxzoom` は**使われない**。ラベルのみ `vt-label-minzoom` / `vt-label-maxzoom` で制御する。
- Polygon では塗り（fill）と外周線（line）の両方に同じ値が適用される。

---

## 5. 点レイヤ（Point）

FlatGeobuf 出力の点ベクタ。MapLibre の `circle` レイヤ1枚（＋ラベル `symbol` 1枚）に展開される。

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `circle-color` | string | `"#e63946"` | `#rrggbb` | `txtPointColor` | 円の塗り色。色分けルール有効時は式に置換される |
| `circle-radius` | number | `8` | 2–30（整数） | `spinPointSize` | 円の半径（px）。**色分けルールでは変えられない** |
| `circle-stroke-color` | string | `"#ffffff"` | `#rrggbb` | `txtPointStroke` | 縁取り色 |
| `circle-stroke-width` | number | `1.5` | 0以上 | **UIなし** | 縁取り幅（px）。ファイル編集でのみ変更可能 |
| `minzoom` | number | `0` | 0–24 | `spinPointMinZoom` | 表示開始ズーム |
| `maxzoom` | number | `24` | 0–24 | `spinPointMaxZoom` | 表示終了ズーム |

### 生成される MapLibre レイヤ

| レイヤID | type | 用途 |
| --- | --- | --- |
| `{layer_id}` | `circle` | 本体。ポップアップ対象 |
| `{layer_id}_label` | `symbol` | `label-enabled` かつ `label-field` が非空のときのみ生成 |

生成される `paint`:

```
circle-color          ← circle-color（色分けルール適用可）
circle-radius         ← circle-radius（固定値のみ）
circle-stroke-color   ← circle-stroke-color（固定値のみ）
circle-stroke-width   ← circle-stroke-width（ルールの width で上書き可）
circle-opacity        ← 1.0 固定（ルールの opacity で上書き可）
circle-stroke-opacity ← 1.0 固定（ルールの opacity で上書き可）
```

> **重要**: 点の不透明度には UI 項目がなく、既定値 `1.0` はコード側にハードコードされている。半透明にしたい場合は色分けルールの `opacity` で上書きするか、`circle-color` を `rgba()` 表記で書く。

---

## 6. 線レイヤ（LineString）

FlatGeobuf 出力の線ベクタ。MapLibre の `line` レイヤ1枚（＋ラベル `symbol` 1枚）に展開される。

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `line-color` | string | `"#1d6fa4"` | `#rrggbb` | `txtLineColor` | 線色。色分けルール適用可 |
| `line-width` | number | `2.0` | 0.5–20.0（刻み0.5） | `spinLineWidth` | 線幅（px）。ルールの `width` で上書き可 |
| `line-casing-color` | string | `"#000000"` | `#rrggbb` | **UIなし** | 縁取り（casing）の色。ルールの `casing_color` で上書き可 |
| `line-casing-width` | number | `0.0` | 0以上 | **UIなし** | 縁取りの総幅（px）。**0 なら縁取り無し**。ルールの `casing_width` で上書き可 |
| `line-opacity` | number | `1.0` | 0.0–1.0（刻み0.1） | `spinLineOpacity` | 不透明度。ルールの `opacity` で上書き可 |
| `line-dasharray` | array of number | `[]` | 正の数を2個以上 | `cmbLineStyle` / `txtLineDash` | **破線パターン**。`[]` は実線。単位は**線幅の倍数**（[6.1](#61-破線-line-dasharray)） |
| `minzoom` | number | `0` | 0–24 | `spinLineMinZoom` | 表示開始ズーム |
| `maxzoom` | number | `24` | 0–24 | `spinLineMaxZoom` | 表示終了ズーム |

### 生成される MapLibre レイヤ

| レイヤID | type | 用途 |
| --- | --- | --- |
| `{layer_id}` | `line` | 本体。ポップアップ対象 |
| `{layer_id}_dash1`, `_dash2`, … | `line` | 区分ごとに破線パターンが違う場合のみ（[6.1](#61-破線-line-dasharray)） |
| `{layer_id}_label` | `symbol` | ラベル有効時のみ |

### 6.1 破線 `line-dasharray`

値は **線幅の倍数** の配列で、線分長と間隔を交互に並べる（MapLibre の
`line-dasharray` と同じ表現）。ピクセルではないので、線を太くすると
破線も比例して大きくなる。`[]` または未指定なら実線で、その場合
`line-dasharray` は `paint` に出力されない。

| 線種 | パターン |
| --- | --- |
| 実線 | `[]` |
| 破線 | `[4, 2]` |
| 点線 | `[1, 2]` |
| 一点鎖線 | `[4, 2, 1, 2]` |
| 二点鎖線 | `[4, 2, 1, 2, 1, 2]` |

比率は Qt（QGIS）の `QPen` 既定パターンと同じなので、QGIS の線種と見た目が揃う。

#### 区分ごとに違う破線

**MapLibre の `line-dasharray` はデータ駆動式（`match` / `step`）を受け付けない**
（ズーム関数のみ）。そのため `vt-color-rules[].dasharray` を使うと、
`_build_line_layers()` が **パターンごとに `filter` 付きの `line` レイヤへ分割**する。

* 既定パターンのレイヤ（`{layer_id}`）… どの「別パターン区分」にも該当しない地物
* `{layer_id}_dash1`, `_dash2`, … … 各パターンの区分だけを通す `filter` 付き

`filter` は色分けと同じ判定（文字列ルールは `match`、数値ルールは区間比較）で
作られるため、**色・幅・破線が必ず同じルール由来になる**。地物が2枚以上の
レイヤで重ね描きされることもない。

---

## 7. 面レイヤ（Polygon）

FlatGeobuf 出力の面ベクタ。MapLibre の `fill` + `line`（外周線）の**2枚**に展開される。

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `fill-color` | string | `"#2d8a4e"` | `#rrggbb` | `txtFillColor` | 塗り色。色分けルール適用可 |
| `fill-opacity` | number | `0.5` | 0.0–1.0（刻み0.1） | `spinFillOpacity` | 塗りの不透明度。ルールの `opacity` で上書き可 |
| `fill-outline-color` | string | `"#ffffff"` | `#rrggbb` | `txtOutlineColor` | **外周線の色**（MapLibre の `fill-outline-color` ではなく、別レイヤの `line-color` に渡される） |
| `line-opacity` | number | `1.0` | 0.0–1.0（刻み0.1） | `spinOutlineOpacity` | **外周線**の不透明度 |
| `line-width` | number | `1.0` | 0以上 | **UIなし** | **外周線の幅**（px）。ファイル編集でのみ変更可能。ルールの `width` で上書き可 |
| `line-dasharray` | array of number | `[]` | 正の数を2個以上 | `cmbOutlineStyle` / `txtOutlineDash` | **外周線の破線パターン**（線幅の倍数）。[6.1](#61-破線-line-dasharray) と同じ規則 |
| `minzoom` | number | `0` | 0–24 | `spinPolygonMinZoom` | 表示開始ズーム |
| `maxzoom` | number | `24` | 0–24 | `spinPolygonMaxZoom` | 表示終了ズーム |

### 生成される MapLibre レイヤ

| レイヤID | type | paint | 用途 |
| --- | --- | --- | --- |
| `{layer_id}` | `fill` | `fill-color`, `fill-opacity` | 塗り。ポップアップ対象 |
| `{layer_id}_outline` | `line` | `line-color`(=`fill-outline-color`), `line-width`, `line-opacity`, `line-dasharray` | 外周線 |
| `{layer_id}_outline_dash1`, … | `line` | 同上＋別の `line-dasharray` | 区分ごとに外周線の破線が違う場合のみ |
| `{layer_id}_label` | `symbol` | — | ラベル有効時のみ |

> **面レイヤでの `line-*` キーは「外周線の設定」を意味する。** 線レイヤ（`geom: "LineString"`）の同名キーとは対象レイヤが違うので混同しないこと。とくに `line-width` は UI に無いため、外周線を太くしたい場合は本ファイルに手で追記する運用になる。
>
> **UI が無くても値は消えない。** `_apply_style_to_layer()` は Polygon に対して `line-width` を書き込まないため、
> `.fgstyle` から読み込んだ外周線幅は「このレイヤにスタイルを適用」を押しても保持され、そのまま `_build_html()` に渡る。
> （検証: `line-width: 3.5` を読込 → レイヤ選択 → 適用 → 出力、の全段階で 3.5 のまま。
> `fill-color` などUIを持つキーだけが UI 値で上書きされる。）
> したがって QML → `.fgstyle` 変換で枠幅を指定する場合、**本体側の改修は不要**。

---

## 8. ラベル（点・線・面 共通）

`geom` が `"Point"` / `"LineString"` / `"Polygon"` のときのみ有効。VectorTile は [9章](#9-ベクトルタイルvectortile)の `vt-label-*` を使う。

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `label-enabled` | boolean | `false` | — | `chkLabelEnabled` | ラベル表示の ON/OFF |
| `label-field` | string | `""` | 属性フィールド名 | `cmbLabelField` | ラベルに使う属性名。**空文字ならラベルレイヤ自体が生成されない** |
| `text-size` | number | `12` | 6–48（整数） | `spinLabelSize` | 文字サイズ（px） |
| `text-color` | string | `"#222222"` | `#rrggbb` | `txtLabelColor` | 文字色 |
| `text-halo-enabled` | boolean | `true` | — | `chkLabelHalo` | 縁取り ON/OFF（[付録B](#付録b-既知の注意点落とし穴)参照） |
| `text-halo-color` | string | `"#ffffff"` | `#rrggbb` | `txtLabelHaloColor` | 縁取り色 |
| `text-halo-width` | number | `1.5` | 0.0–8.0（刻み0.5） | `spinLabelHaloWidth` | 縁取り幅（px） |
| `text-minzoom` | number | `0` | 0–24 | `spinLabelMinZoom` | ラベル表示開始ズーム |
| `text-maxzoom` | number | `24` | 0–24 | `spinLabelMaxZoom` | ラベル表示終了ズーム |

生成される `symbol` レイヤの `layout` は固定で以下を含む。

```json
{
  "text-field": ["to-string", ["get", "<label-field>"]],
  "text-font": ["Open Sans Regular"],
  "text-size": 12,
  "text-allow-overlap": false
}
```

- `text-font` と `text-allow-overlap` は本ファイルからは変更できない。
- `["to-string", ...]` により数値属性もそのまま表示できる。

---

## 9. ベクトルタイル（VectorTile）

`geom: "VectorTile"`。1ソースにつき `vt-geom-type` で選んだ**単一のジオメトリ種別**のみを描画する。

### 9.1 ソース定義

| キー | 型 | 既定値 | 対応UI | 説明 |
| --- | --- | --- | --- | --- |
| `tile_url` | string | レイヤソースから自動抽出 | `txtVtUrl` | タイル URL テンプレート（`{z}/{x}/{y}`）。**読込時はファイルの値が無視され、現在のレイヤの値が保持される** |
| `vt-source` | string | `""` | `txtVtSource` | MapLibre のソース ID。空なら `layer_id` が使われる。生成レイヤ ID の接頭辞にもなる |
| `vt-source-layer` | string | `""` | `txtVtSourceLayer` | **必須**。MVT 内のレイヤ名。空のまま HTML 出力すると `ValueError: VectorTileのsource-layerが未指定` で失敗する |
| `vt-geom-type` | string | `"Polygon"` | `cmbVtGeomType` | `"Polygon"` / `"LineString"` / `"Point"` のいずれか。**この値以外のジオメトリは描画されない** |

### 9.2 面（`vt-geom-type: "Polygon"`）

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `fill-color` | string | `"#2d8a4e"` | `#rrggbb` | `txtVtFillColor` | 塗り色。色分けルール適用可 |
| `fill-opacity` | number | `0.6` | 0.0–1.0 | `spinVtFillOpacity` | 塗りの不透明度。ルールの `opacity` で上書き可 |
| `vt-outline-color` | string | `"#ffffff"` | `#rrggbb` | `txtVtOutlineColor` | 外周線の色（固定値のみ） |
| `vt-outline-width` | number | `1.0` | 0.0–10.0（刻み0.5） | `spinVtOutlineWidth` | 外周線の幅。ルールの `width` で上書き可 |
| `vt-outline-dasharray` | array of number | `[]` | 正の数を2個以上 | `cmbVtOutlineStyle` / `txtVtOutlineDash` | 外周線の破線パターン（線幅の倍数） |

生成レイヤ: `{source}_fill`（fill）+ `{source}_outline`（line）

### 9.3 線（`vt-geom-type: "LineString"`）

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `vt-line-color` | string | `"#1d6fa4"` | `#rrggbb` | `txtVtLineColor` | 線色。色分けルール適用可 |
| `vt-line-width` | number | `2.0` | 0.5–20.0（刻み0.5） | `spinVtLineWidth` | 線幅。ルールの `width` で上書き可 |
| `vt-line-opacity` | number | `1.0` | 0.0–1.0 | `spinVtLineOpacity` | 不透明度。ルールの `opacity` で上書き可 |
| `vt-line-dasharray` | array of number | `[]` | 正の数を2個以上 | `cmbVtLineStyle` / `txtVtLineDash` | 破線パターン（線幅の倍数） |

生成レイヤ: `{source}_line`（line）

### 9.4 点（`vt-geom-type: "Point"`）

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `vt-circle-color` | string | `"#e63946"` | `#rrggbb` | `txtVtPointColor` | 円の塗り色。色分けルール適用可 |
| `vt-circle-radius` | number | `6` | 2–30（整数） | `spinVtPointRadius` | 円の半径（px）。固定値のみ |
| `vt-circle-stroke` | string | `"#ffffff"` | `#rrggbb` | `txtVtPointStroke` | 縁取り色。固定値のみ |
| `vt-tree-svg-enabled` | boolean | `false` | — | `chkVtTreeSvg` | 単木 SVG アイコン表示（有償オプション `treesvg.js`） |

生成レイヤ: `{source}_circle`（circle）、単木 SVG 有効時はさらに `{source}_tree`（symbol）

点の `circle-stroke-width` / `circle-opacity` / `circle-stroke-opacity` は**キーを持たず**、既定 `1.5` / `1.0` / `1.0` がコードにハードコードされている。色分けルールの `width` / `opacity` を使えば属性値ごとに変えられる。

#### `vt-tree-svg-enabled` を有効にした場合の特例

- フォールバックの円は **黒（`#000000`）固定** になり、**色分けルールより優先される**。
- 円の半径は `circle-radius` ではなく、属性フィールド **`樹高`** から実寸換算される（`TREE_SVG_FIELDS["height"]`、Nodata 時は 10.0 m）。
- SVG アイコンは `樹種`（色）、`樹冠長率`（形状3段階、Nodata 時 40.0）を参照する。ズーム16未満は樹冠のみ、16以上は樹幹＋樹冠。
- これらのフィールド名・既定値は `.fgstyle` からは変更できない（`dialog.py` の定数）。

### 9.5 ラベル（VectorTile 用）

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `vt-label-enabled` | boolean | `false` | — | `chkVtLabelEnabled` | ラベル表示 ON/OFF |
| `vt-label-field` | string | `""` | 属性名 | `txtVtLabelField` | 空ならラベルレイヤは生成されない |
| `vt-label-size` | number | `12` | 6–48（整数） | `spinVtLabelSize` | 文字サイズ |
| `vt-label-color` | string | `"#222222"` | `#rrggbb` | `txtVtLabelColor` | 文字色 |
| `vt-label-halo` | boolean | `true` | — | `chkVtLabelHalo` | 縁取り ON/OFF。**`false` なら halo 色が `rgba(0,0,0,0)`、幅が `0` になる** |
| `vt-label-halo-color` | string | `"#ffffff"` | `#rrggbb` | `txtVtLabelHaloColor` | 縁取り色 |
| `vt-label-minzoom` | number | `0` | 0–24 | `spinVtLabelMinZoom` | ラベル表示開始ズーム |
| `vt-label-maxzoom` | number | `24` | 0–24 | `spinVtLabelMaxZoom` | ラベル表示終了ズーム |

生成レイヤ: `{source}_label`（symbol）

> VectorTile の**縁取り幅は `1.5` 固定**（`vt-label-halo` が `true` のとき）で、対応キーは存在しない。fgb 側の `text-halo-width` に相当するものがない点に注意。

### 9.6 生成レイヤ ID 一覧（VectorTile）

`{source}` = `vt-source` が非空ならその値、空なら `layer_id`。

| ID | type | 生成条件 |
| --- | --- | --- |
| `{source}_fill` | fill | `vt-geom-type == "Polygon"` |
| `{source}_outline` | line | `vt-geom-type == "Polygon"` |
| `{source}_line` | line | `vt-geom-type == "LineString"` |
| `{source}_circle` | circle | `vt-geom-type == "Point"` |
| `{source}_tree` | symbol | `vt-geom-type == "Point"` かつ `vt-tree-svg-enabled` |
| `{source}_label` | symbol | `vt-label-enabled` かつ `vt-label-field` が非空 |

ポップアップ対象は `type != "symbol"` のレイヤのみ（＝ラベルと単木アイコンはクリック対象外）。

---

## 10. ラスタ（Raster / Raster(Tile)）

| キー | 型 | 既定値 | 範囲 | 対応UI | 説明 |
| --- | --- | --- | --- | --- | --- |
| `raster-opacity` | number | `1.0` | 0.0–1.0（刻み0.1） | `spinRasterOpacity` | 不透明度 |
| `minzoom` | number | `0` | 0–24 | `spinRasterMinZoom` | 表示開始ズーム |
| `maxzoom` | number | `24` | 0–24 | `spinRasterMaxZoom` | 表示終了ズーム |

- `geom` は `"Raster"`（ファイル）または `"Raster(Tile)"`（XYZ / WMS）。両者でキー構成は同一。
- ラスタには色分けルール・ラベルは適用されない。

---

## 11. 属性値色分けルール `vt-color-rules`

**点・線・面・ベクトルタイルのすべてで共通**のキー群。歴史的経緯でベクトルタイル用に作られたため、FlatGeobuf ベクタでも `vt-` プレフィックスのままである。

| キー | 型 | 既定値 | 対応UI | 説明 |
| --- | --- | --- | --- | --- |
| `vt-color-rule-enabled` | boolean | `false` | `chkVtColorRule` | `false` ならルールは**完全に無視**され、既定色の単色描画になる |
| `vt-color-rule-field` | string | `""` | `txtVtColorRuleField` | 判定に使う属性フィールド名。**空文字ならルールは無視**される |
| `vt-color-rules` | array of object | `[]` | `tblVtColorRules` | ルールの配列。**配列の順序に意味がある**（文字列モード時） |

### 11.1 ルールオブジェクトのスキーマ

```json
{
  "value":   "スギ",
  "num_min": 20,
  "num_max": 30,
  "color":   "#2d8a4e",
  "opacity": 0.8,
  "width":   2.5
}
```

| キー | 型 | 必須 | 説明 |
| --- | --- | --- | --- |
| `color` | string | **必須** | 適用する色（`#rrggbb`）。UI から追加した行の初期値は `#cccccc` |
| `value` | string | 文字列モードで必須 | 完全一致で判定する属性値。**`""`（空文字）も有効な条件**で、属性が空欄／NULL の地物にマッチする |
| `num_min` | number \| string | 数値モードで必須 | 区間の下限。**この値以上**が該当。数値に変換できない文字列が入った場合は文字列のまま保持される |
| `num_max` | number \| string | 任意 | 区間の上限。**描画には使われず、凡例ラベルの生成にのみ使われる**（[11.4](#114-数値モードの区間の考え方)参照） |
| `opacity` | number | 任意 | この区分だけの不透明度。省略時は上段の既定値を継承 |
| `width` | number | 任意 | この区分だけの線幅／枠幅。省略時は上段の既定値を継承 |
| `dasharray` | array of number | 任意 | この区分だけの破線パターン（線幅の倍数）。キーがあれば `[]` でも「明示的に実線」として扱われ、レイヤ既定の破線を打ち消す。パターンごとに `filter` 付きレイヤへ分割される（[6.1](#61-破線-line-dasharray)） |
| `label` | string | 任意 | 凡例（WEB地図のレイヤパネル）に表示する名前。**空文字または未指定なら `value` または数値範囲から自動生成**（[12章](#12-凡例の生成規則)参照）。UI の列6「凡例表示名」と往復する |
| `casing_color` | string | 任意 | **縁取り（casing）の色**。`shape` が線のときのみ。下に敷く太い線の色 |
| `casing_width` | number | 任意 | **縁取りの総幅（px）**。0 または未指定なら縁取り無し。中心線の幅（`width`）より太くする |
| `outline_color` | string | 任意 | **面の外周線の色**。QGISは「塗りと同じ色で縁取る」定義が多いため、区分ごとに持てる。省略時は `fill-outline-color` / `vt-outline-color` |

> **`label` について**: QGIS から変換したスタイルでは「判定値」と「凡例名」が別物なことが多い
> （例: 判定は `ser = 619`、凡例は `K21_vas_ap`）。`fgstyle Maker` プラグインは QML の
> `label` 属性をこのキーへ書き出す。
> 旧版の ForestGeo Studio（列6を持たないもの）では未知キーとして無視されるだけなので、
> ファイルの互換性は保たれる（凡例が自動生成に戻るのみ）。

### 11.2 モード判定

```
配列 vt-color-rules のいずれかの要素が
  "num_min" または "num_max" キーを持つ  →  数値モード
それ以外                                  →  文字列モード
```

**モードは配列全体で1つに決まる。文字列ルールと数値ルールの混在はできない。**
混在させた場合は数値モードとして扱われ、`num_min` を持たない行は描画式から**黙って除外**される（凡例には残るため、凡例と地図が食い違う）。

### 11.3 文字列モード → MapLibre `match` 式

```
["match", ["to-string", ["coalesce", ["get", <field>], ""]],
  <value1>, <color1>,
  <value2>, <color2>,
  ...
  <既定色>]
```

- **配列の上から順に評価され、最初に一致したものが採用される。**
- `["coalesce", ["get", field], ""]` により、属性が NULL の地物は `""` として扱われる。したがって `"value": ""` のルールを1行置けば「空欄の地物」に色を付けられる。
- `["to-string", …]` により、**属性が数値型でも文字列ルールに一致する**（`619` → `"619"`）。MapLibre の `match` は型に厳密なので、この変換が無いと数値属性はどのルールにも当たらず既定色になる（[付録B #13b](#付録b-既知の注意点落とし穴)）。
- どのルールにも一致しない地物は既定色（`fill-color` / `line-color` / `circle-color` 等）になる。
- 完全一致のみ。部分一致・大小文字無視・正規表現は不可。

### 11.4 数値モード → MapLibre `step` 式

```
["step", ["to-number", ["coalesce", ["get", <field>], -1000000000], -1000000000],
  <既定色>,
  <num_min1>, <color1>,
  <num_min2>, <color2>,
  ...]
```

入力を `to-number` で包むのは、**属性が文字列型でも数値ルールが効くようにする**ため。
`"4"`（文字列）も `4`（数値）も `4` になる。属性が無い／NULL、または数値に変換できない
文字列（`"abc"`、全角数字 `"４"`）は番兵値 `-1000000000` になり、全区分の下限より
小さいので既定色（＝該当なし）へ落ちる。空文字 `""` は ECMAScript の規則で `0` になる。

処理手順：

1. `num_min` を持つ行だけを抽出する（**`num_max` しか持たない行はここで落ちる**）。
2. `num_min` の**昇順にソート**する（ファイル上の並び順は無視される）。
3. `step` 式に展開する。

#### 区間の考え方

| 属性値 | 適用される色 |
| --- | --- |
| `< num_min1` | 既定色 |
| `num_min1 <= 値 < num_min2` | `color1` |
| `num_min2 <= 値 < num_min3` | `color2` |
| `>= 最後の num_min` | 最後の色 |

> **`num_max` は描画に一切影響しない。** 実際の区間の上限は「次の行の `num_min`」で決まる。
> したがって **`num_max` は次の行の `num_min` と一致させて書く**のが正しい運用であり、隙間を空けると（例: `0–10`, `20–30`）その隙間（`10–20`）は前の区間の色で塗られる。
> `num_max` は凡例に `20～30` と表示するためだけに保持されている。

#### 最小値未満の扱い

最小の `num_min` より小さい値は**既定色**になる。「〇〇未満」に明示的な色を付けたい場合は `num_min: -999999` のような十分小さい下限を持つ行を追加する。

### 11.5 `opacity` / `width` の上書き

色とは独立に、属性値ごとに不透明度・線幅を切り替えられる。

| 条件 | 生成される値 |
| --- | --- |
| どのルールも `opacity`（`width`）を持たない、または空 | 上段の既定値（スカラー）をそのまま使う。**式を作らない** |
| 1つでも持つ | 色分けと同じ `match` / `step` 構造の**数値式**を生成。値を持たない行には上段の既定値が入る |

`width` / `opacity` がどのプロパティに効くかはジオメトリ種別で異なる。

| `geom` / `vt-geom-type` | `width` の効き先 | `opacity` の効き先 | `width` の既定値 |
| --- | --- | --- | --- |
| Point（fgb） | `circle-stroke-width` | `circle-opacity` + `circle-stroke-opacity` | `circle-stroke-width`（既定 1.5） |
| LineString（fgb） | `line-width` | `line-opacity` | `line-width`（既定 2.0） |
| Polygon（fgb） | 外周線の `line-width` | `fill-opacity` | `line-width`（既定 1.0） |
| VectorTile / Point | `circle-stroke-width` | `circle-opacity` + `circle-stroke-opacity` | `1.5`（固定） |
| VectorTile / LineString | `line-width` | `line-opacity` | `vt-line-width`（既定 2.0） |
| VectorTile / Polygon | `vt-outline-width` | `fill-opacity` | `vt-outline-width`（既定 1.0） |

数値に変換できない `opacity` / `width` の値は、その行だけ既定値にフォールバックする（エラーにはならない）。

### 11.6 UI 表（`tblVtColorRules`）との対応

| 列 | 見出し | 対応キー | 空欄時の意味 |
| --- | --- | --- | --- |
| 0 | 属性値（文字列） | `value` | `""` として保持（＝空欄条件） |
| 1 | 数値下限 | `num_min` | キー自体を出力しない |
| 2 | 数値上限 | `num_max` | キー自体を出力しない |
| 3 | 色 | `color` | **空だとその行は丸ごと無視される** |
| 4 | 不透明度（空欄=既定） | `opacity` | キーを出力しない（＝上段の既定値を継承） |
| 5 | 枠幅／ライン幅（空欄=既定） | `width` | キーを出力しない（＝上段の既定値を継承） |
| 6 | 凡例表示名（空欄=自動） | `label` | キーを出力しない（＝`value`／数値範囲から自動生成） |
| 7 | 線種（空欄=既定） | `dasharray` | キーを出力しない（＝レイヤ既定の線種を継承） |

UI からの収集（`_vt_collect_rules`）の規則：

- 列1・列2 の**いずれかが非空**なら数値ルールとして出力（このとき `value` は `""` で出力される）。
- 両方空なら文字列ルールとして出力。
- **`color` が空の行は出力されない。**
- `opacity` / `width` が数値変換に失敗した場合、そのキーは出力されない。
- 列6 は前後空白を除いて非空なら `label` として出力。凡例では `value` / 数値範囲より**優先**される。
- 列7 は `実線` / `solid` / `なし` / `0` のいずれかなら `"dasharray": []`（＝明示的に実線）、
  `4, 2` のようなカンマ区切り数値なら `"dasharray": [4, 2]`。空欄ならキーを出力しない。

> 列6・列7 は、破線対応版の ForestGeo Studio 本体（`tblVtColorRules` が8列のもの）で追加された。
> 6列の旧版で読み込んだ場合、`label` / `dasharray` は保持されず「適用」時に失われる。

---


## 11.7 縁取り（casing）

道路記号のように「太い線の上に細い線を重ねて縁取りを作る」表現に使う。
MapLibre では **太い線のレイヤを下に敷き、その上に本線のレイヤを描く**のが定石で、
`.fgstyle` もその形に落とす。

```json
{ "value": "1", "color": "#6abc6e", "width": 3.0,
  "casing_color": "#675f80", "casing_width": 4.5 }
```

| 生成されるレイヤ | type | 順序 | 内容 |
| --- | --- | --- | --- |
| `{layer_id}_casing` | `line` | **本線より前（＝下）** | `casing_color` / `casing_width` |
| `{layer_id}` ほか | `line` | 上 | `color` / `width` / `dasharray` |

* `casing_width` は**線の総幅**（中心線＋左右の縁取り）。MapLibre の `line-width` と同じ意味なので、
  QGISの縁取り線の幅をそのまま入れればよい。中心線の `width` より太くすること。
* 縁取りを持たない区分は幅0になるため何も描かれない。
  したがって1つのレイヤ内で「縁取りのある区分」と「無い区分」を混在させられる。
* レイヤ全体で共通の縁取りは `line-casing-*` / `vt-line-casing-*` で指定する。
* 縁取りレイヤは**1枚だけ**で、破線の分割（[11.6](#116-ui-表tblvtcolorrulesとの対応)）は行わない。
  縁取りは実線が前提。
* 不透明度は本線と同じ値（`line-opacity` / `vt-line-opacity`）を使う。専用キーは持たない。

> **なぜ必要か**: QGISは同じ条件のスタイルを2枚重ねて縁取りを作る。
> 単純に「先に書いたほうが勝ち」で1枚に丸めると、**太い縁取りだけが残って
> 中心線の色が失われる**（道路が全部くすんだ太線になる）。

---
## 12. 凡例の生成規則

`_build_legend()` は `.fgstyle` の内容から凡例アイテム配列を組み立てる。

```json
[{ "label": "スギ", "color": "#2d8a4e", "shape": "fill" },
 { "label": "伏在断層", "color": "#000000", "shape": "line", "dash": [3.75, 1.667] }]
```

| キー | 型 | 説明 |
| --- | --- | --- |
| `label` | string | レイヤパネルに出す名前 |
| `color` | string | 色見本の色（`#rrggbb`）|
| `shape` | string | `"fill"` / `"line"` / `"circle"` |
| `dash` | array of number | **`shape: "line"` のみ**。破線パターン（線幅の倍数）。レイヤパネルの色見本をSVGの線で描き、実線・破線・点線を見分けられるようにする。省略・空なら実線 |

`dash` は描画側と同じ値（ルールの `dasharray`、無ければレイヤ既定の `line-dasharray` /
`vt-line-dasharray` / `vt-outline-dasharray`）が入る。
色見本の幅は限られるため、**凡例全体で共通の係数**をかけて縮小表示する
（いちばん長いパターンでも2周期入るようにする）。共通係数なので
「短い破線／長い破線」の区別はそのまま残る。

| 優先 | 条件 | 生成内容 |
| --- | --- | --- |
| 1 | `vt-legend` が非空の配列 | **その配列をそのまま凡例に使う**（[15.4](#154-追加キー)） |
| 2 | `vt-color-rule-enabled` が `true` かつ `vt-color-rules` が非空かつ `vt-color-rule-field` が非空 | **ルール1行につき凡例1件** |
| 3 | 上記以外 | 既定色の**単色アイテム1件**（`label` は `""`） |

### `shape` の決定

| ジオメトリ | `shape` | 既定色の取得元 |
| --- | --- | --- |
| Polygon | `"fill"` | `fill-color` |
| LineString | `"line"` | `vt-line-color` → `line-color` の順 |
| その他（Point 等） | `"circle"` | `vt-circle-color` → `circle-color` の順 |

いずれの経路でも、`color` が文字列でない（MapLibre 式の配列などの）場合は上表の既定色へ落とす。
既定色自体が式の場合は `#cccccc` になる。

### `label` の決定

| ルール種別 | ラベル |
| --- | --- |
| `label` キーが非空 | **`label` をそのまま**（他の判定より優先） |
| 文字列ルール | `value` をそのまま |
| 数値ルール（`num_min` と `num_max` 両方） | `"20～30"` |
| 数値ルール（`num_min` のみ） | `"20～"` |
| 数値ルール（`num_max` のみ） | `"～30"` |
| 数値ルール（どちらも空） | `""` |

数値は整数と等しい float なら整数表記になる（`20.0` → `20`）。

### 重複行のまとめ

**`label`・色見本・線種がすべて同じ行は、凡例では1行にまとめられる**（先に出てきた方を残す）。
描画ルールはそのまま全件効く。

これは判定値の表記ゆれ対策で「同じ色・同じ凡例名の別名ルール」を並べたときに、
レイヤパネルへ同じ項目が二重に出るのを防ぐため。

```
ルール: '１２３'(赤/スギ林)、'123'(赤/スギ林)、' ヒノキ '(緑/ヒノキ林)、'ヒノキ'(緑/ヒノキ林)、'456'(青/その他)
   → 描画は5ルールとも有効
   → 凡例は  スギ林 / ヒノキ林 / その他  の3行
```

`label` を付けずに判定値をそのまま凡例名にしている場合は、値が違えば別行のままになる。
別名ルールを凡例から消したいなら `label` を揃えること。

> **凡例と描画のずれに注意**: 凡例は `vt-color-rules` を**ファイル記載順のまま**列挙するが、数値モードの描画は `num_min` 昇順にソートされる。凡例の並びを描画と一致させたい場合は、はじめから `num_min` 昇順で書くこと。

---

## 13. 読み込み時の挙動と互換性

### 13.1 マージ規則

```
new_style = dict(現在のスタイル)
new_style.update(ファイルの style)
if 現在のgeomが非空:  new_style["geom"]      = 現在のgeom
if 現在にtile_urlあり: new_style["tile_url"] = 現在のtile_url
```

これにより：

| 性質 | 説明 |
| --- | --- |
| **部分ファイルはパッチとして働く** | ファイルに書かれていないキーは現在の値が残る。「線色だけ差し替える」ような最小ファイルが作れる |
| **`geom` は必ずレイヤ側が勝つ** | ファイルの `geom` でレイヤ種別が書き換わることはない |
| **`tile_url` は必ずレイヤ側が勝つ** | 別サーバのタイル URL が意図せず流入しない |
| **未知のキーは黙って保持される** | 実装が知らないキーもスタイル辞書に残るが、HTML 生成では参照されない（無害） |

### 13.2 バージョン

- `_version` は現行 `1`。**読み込み時に検証されない**ため、`_version: 2` のファイルもエラーにはならず読める。
- 将来キーを追加する場合、既存実装は未知キーを無視するだけなので、**キー追加は後方互換**である。
- キーの**意味を変える**変更（例: `num_max` を描画に効かせる）は互換性を壊すため、`_version` を上げたうえで読込側に分岐を入れる必要がある。

---

## 14. 実例 JSON サンプル集

### 14.1 点（単色 + ラベル）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "毎木調査点",
  "geom": "Point",
  "style": {
    "geom": "Point",
    "circle-color": "#e63946",
    "circle-radius": 6,
    "circle-stroke-color": "#ffffff",
    "circle-stroke-width": 1.5,
    "minzoom": 12,
    "maxzoom": 24,
    "label-enabled": true,
    "label-field": "樹種",
    "text-size": 11,
    "text-color": "#222222",
    "text-halo-enabled": true,
    "text-halo-color": "#ffffff",
    "text-halo-width": 1.5,
    "text-minzoom": 16,
    "text-maxzoom": 24,
    "vt-color-rule-enabled": false,
    "vt-color-rule-field": "",
    "vt-color-rules": []
  }
}
```

### 14.2 点（樹種別の文字列色分け・空欄行あり）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "毎木調査点（樹種別）",
  "geom": "Point",
  "style": {
    "geom": "Point",
    "circle-color": "#999999",
    "circle-radius": 7,
    "circle-stroke-color": "#ffffff",
    "circle-stroke-width": 1.0,
    "minzoom": 0,
    "maxzoom": 24,
    "label-enabled": false,
    "label-field": "",
    "vt-color-rule-enabled": true,
    "vt-color-rule-field": "樹種",
    "vt-color-rules": [
      { "value": "スギ",   "color": "#2d8a4e", "width": 1.5 },
      { "value": "ヒノキ", "color": "#7cb342", "width": 1.5 },
      { "value": "カラマツ", "color": "#c0a020", "width": 1.0 },
      { "value": "広葉樹", "color": "#8d6e63", "width": 1.0 },
      { "value": "",       "color": "#cccccc", "opacity": 0.4 }
    ]
  }
}
```

- 最終行の `"value": ""` は**属性が空欄／NULL の地物**にマッチする。
- `width` は縁取り幅、`opacity` は円と縁取りの両方に効く。

### 14.3 線（林道・規格別の線幅切替）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "林道網",
  "geom": "LineString",
  "style": {
    "geom": "LineString",
    "line-color": "#1d6fa4",
    "line-width": 2.0,
    "line-opacity": 1.0,
    "minzoom": 0,
    "maxzoom": 24,
    "label-enabled": true,
    "label-field": "路線名",
    "text-size": 12,
    "text-color": "#1d6fa4",
    "text-halo-enabled": true,
    "text-halo-color": "#ffffff",
    "text-halo-width": 2.0,
    "text-minzoom": 14,
    "text-maxzoom": 24,
    "vt-color-rule-enabled": true,
    "vt-color-rule-field": "規格",
    "vt-color-rules": [
      { "value": "1級", "color": "#b71c1c", "width": 5.0, "opacity": 1.0 },
      { "value": "2級", "color": "#ef6c00", "width": 3.5, "opacity": 1.0 },
      { "value": "3級", "color": "#1d6fa4", "width": 2.0, "opacity": 0.9 },
      { "value": "作業道", "color": "#757575", "width": 1.0, "opacity": 0.7 }
    ]
  }
}
```

### 14.4 面（林齢による数値色分け）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "林小班",
  "geom": "Polygon",
  "style": {
    "geom": "Polygon",
    "fill-color": "#cccccc",
    "fill-opacity": 0.6,
    "fill-outline-color": "#333333",
    "line-opacity": 0.8,
    "line-width": 1.0,
    "minzoom": 0,
    "maxzoom": 24,
    "label-enabled": true,
    "label-field": "小班番号",
    "text-size": 12,
    "text-color": "#111111",
    "text-halo-enabled": true,
    "text-halo-color": "#ffffff",
    "text-halo-width": 1.5,
    "text-minzoom": 15,
    "text-maxzoom": 24,
    "vt-color-rule-enabled": true,
    "vt-color-rule-field": "林齢",
    "vt-color-rules": [
      { "value": "", "num_min": 0,  "num_max": 10, "color": "#e8f5e9", "opacity": 0.7 },
      { "value": "", "num_min": 10, "num_max": 20, "color": "#a5d6a7", "opacity": 0.7 },
      { "value": "", "num_min": 20, "num_max": 40, "color": "#4caf50", "opacity": 0.7 },
      { "value": "", "num_min": 40, "num_max": 60, "color": "#2e7d32", "opacity": 0.8 },
      { "value": "", "num_min": 60,                "color": "#1b5e20", "opacity": 0.9, "width": 2.0 }
    ]
  }
}
```

- `num_max` を次の行の `num_min` と**一致させている**ため、隙間なく塗り分けられる。
- 最終行は `num_max` を省略しているので、凡例は `60～` になる。
- `林齢 < 0` は既定色 `#cccccc` になる。

このとき生成される `fill-color` 式：

```json
["step", ["get", "林齢"], "#cccccc",
  0.0, "#e8f5e9",
  10.0, "#a5d6a7",
  20.0, "#4caf50",
  40.0, "#2e7d32",
  60.0, "#1b5e20"]
```

### 14.5 ベクトルタイル（面・地種区分別）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "森林簿タイル",
  "geom": "VectorTile",
  "style": {
    "geom": "VectorTile",
    "tile_url": "https://example.jp/tiles/rinsho/{z}/{x}/{y}.pbf",
    "vt-source": "rinsho",
    "vt-source-layer": "rinshobo",
    "vt-geom-type": "Polygon",
    "fill-color": "#2d8a4e",
    "fill-opacity": 0.6,
    "vt-outline-color": "#ffffff",
    "vt-outline-width": 1.0,
    "vt-label-enabled": true,
    "vt-label-field": "小班",
    "vt-label-size": 12,
    "vt-label-color": "#222222",
    "vt-label-halo": true,
    "vt-label-halo-color": "#ffffff",
    "vt-label-minzoom": 15,
    "vt-label-maxzoom": 24,
    "vt-color-rule-enabled": true,
    "vt-color-rule-field": "地種区分",
    "vt-color-rules": [
      { "value": "人工林", "color": "#2d8a4e", "opacity": 0.7 },
      { "value": "天然林", "color": "#8d6e63", "opacity": 0.7 },
      { "value": "無立木地", "color": "#e0e0e0", "opacity": 0.5 },
      { "value": "竹林",   "color": "#9ccc65", "opacity": 0.7 }
    ]
  }
}
```

### 14.6 ベクトルタイル（点・単木SVGアイコン）

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "単木タイル",
  "geom": "VectorTile",
  "style": {
    "geom": "VectorTile",
    "tile_url": "https://example.jp/tiles/tree/{z}/{x}/{y}.pbf",
    "vt-source": "tree",
    "vt-source-layer": "trees",
    "vt-geom-type": "Point",
    "vt-circle-color": "#e63946",
    "vt-circle-radius": 6,
    "vt-circle-stroke": "#ffffff",
    "vt-tree-svg-enabled": true,
    "vt-label-enabled": false,
    "vt-label-field": "",
    "vt-color-rule-enabled": false,
    "vt-color-rule-field": "",
    "vt-color-rules": []
  }
}
```

> `vt-tree-svg-enabled: true` のとき円は黒固定になるため、`vt-circle-color` と色分けルールは無効になる。

### 14.7 ラスタタイル

```json
{
  "_format": "forestgeostudio-layer-style",
  "_version": 1,
  "_layer_name": "オルソ画像",
  "geom": "Raster(Tile)",
  "style": {
    "geom": "Raster(Tile)",
    "raster-opacity": 0.75,
    "minzoom": 10,
    "maxzoom": 22
  }
}
```

### 14.8 最小構成（パッチ用・ラッパーなし）

線色と線幅だけを差し替える最小ファイル。トップレベルに `geom` があるため受理される（[2章](#2-トップレベル構造)の形態2）。

```json
{
  "geom": "LineString",
  "line-color": "#b71c1c",
  "line-width": 4.0
}
```

読み込むと、`line-opacity` やラベル設定など**ファイルに書かれていない項目は現在の値のまま**残る。

---

## 15. MapLibre式による拡張

`_build_html()` は、スカラーキーの値を **MapLibre の `paint` / `layout` へ
`json.dumps` でそのまま流し込む**。したがって値に **MapLibre式（JSON配列）や
`rgba()` 色**を入れれば、ForestGeo Studio のUIに対応する項目が無くても
WEB地図には反映される。

### 15.1 式を入れられるキー

`_build_html()` が値をそのまま `paint` / `layout` へ渡すキーが対象。

| geom | 式を入れられるキー |
| --- | --- |
| Point | `circle-color` / `circle-radius` / `circle-stroke-color` / `circle-stroke-width` |
| LineString | `line-color` / `line-width` / `line-opacity` |
| Polygon | `fill-color` / `fill-opacity` / `fill-outline-color` / `line-width` / `line-opacity` |
| ラベル共通 | `text-size` / `text-color` / `text-halo-color` / `text-halo-width` |
| VectorTile | `fill-color` / `fill-opacity` / `vt-outline-color` / `vt-outline-width` / `vt-line-*` / `vt-circle-color` / `vt-circle-radius` / `vt-circle-stroke` / `vt-label-size` / `vt-label-color` |

**式を入れてはいけないキー**: `minzoom` / `maxzoom` / `text-minzoom` / `text-maxzoom` /
`vt-label-minzoom` / `vt-label-maxzoom`（`float()` で数値化されるため）、
`geom` / `vt-geom-type` / `vt-source-layer` / `tile_url`（文字列として扱われるため）。

### 15.2 使いどころ

| 目的 | 例 |
| --- | --- |
| 色分けルールでは表現できない条件（複数フィールド・AND/OR） | `"fill-color": ["case", ["all", ["==", ["get","樹種"],"スギ"], [">", ["get","林齢"],40]], "#2d8a4e", "#cccccc"]` |
| カテゴリごとの円の半径（[付録B #7](#付録b-既知の注意点落とし穴) の制限を回避） | `"circle-radius": ["match", ["to-string", ["coalesce", ["get","cls"], ""]], "A", 10, 4]` |
| 点の不透明度（[付録B #8](#付録b-既知の注意点落とし穴) の制限を回避） | `"circle-color": "rgba(230,57,70,0.6)"` |
| マップ単位の実寸をズーム全域で再現 | `"line-width": ["interpolate", ["exponential",2], ["zoom"], 0, 0.0000256, 24, 429.5]` |

### 15.3 制約

* **UIでは編集できない。** 式を含むスタイルをレイヤ選択でプリセットすると、
  現行の `_on_layer_selected()` は `int(list)` で `TypeError` を起こす。
  式を扱うにはUI側の保護パッチが必要（`fgstyle Maker` の README 6.1）。
* 色分けルール（`vt-color-rules`）が有効なキーでは、式は `match` / `step` の
  **フォールバック値**として使われる。ルールと式を同時に使う場合はこの順序に注意する。
* 凡例（`_build_legend()`）は色を文字列として扱うため、式を入れたキーの凡例は
  別途 `vt-legend` キーで与える必要がある。

### 15.4 追加キー

| キー | 位置 | 型 | 説明 |
| --- | --- | --- | --- |
| `vt-legend` | style 直下 | array | 凡例アイテムを直接指定する。`[{"label": str, "color": "#rrggbb", "shape": "fill"\|"line"\|"circle"}, …]`。式でスタイルを組んだ場合に使う |

`vt-legend` は `vt-color-rules` より**優先**される。UI を持たないキーだが、
読み込み時に未知キーとして保持され「適用」でも消えないため、`.fgstyle` に書くだけで効く。
配列でない・空・要素が dict でない場合は無視され、通常のルール由来の凡例に戻る。

> `vt-color-rules[].label`（凡例表示名）は**拡張キーではなくなった**。
> 破線対応版の本体では UI 列6 と `_build_legend()` が正式に対応している（[11.1](#111-ルールオブジェクトのスキーマ) / [12章](#12-凡例の生成規則)）。

---

## 付録A: キー一覧（アルファベット順・逆引き）

| キー | 有効な `geom` | 型 | 既定値 |
| --- | --- | --- | --- |
| `circle-color` | Point | string | `#e63946` |
| `circle-radius` | Point | number | `8` |
| `circle-stroke-color` | Point | string | `#ffffff` |
| `circle-stroke-width` | Point | number | `1.5` |
| `fill-color` | Polygon, VectorTile(Polygon) | string | `#2d8a4e` |
| `fill-opacity` | Polygon, VectorTile(Polygon) | number | `0.5` / VT は `0.6` |
| `fill-outline-color` | Polygon | string | `#ffffff` |
| `geom` | 全種別 | string | — |
| `label-enabled` | Point, LineString, Polygon | boolean | `false` |
| `label-field` | Point, LineString, Polygon | string | `""` |
| `line-color` | LineString | string | `#1d6fa4` |
| `line-dasharray` | LineString, Polygon(外周線) | array | `[]` |
| `line-opacity` | LineString, Polygon(外周線) | number | `1.0` |
| `line-width` | LineString, Polygon(外周線) | number | `2.0` / Polygon は `1.0` |
| `maxzoom` | Point, LineString, Polygon, Raster | number | `24` |
| `minzoom` | Point, LineString, Polygon, Raster | number | `0` |
| `raster-opacity` | Raster, Raster(Tile) | number | `1.0` |
| `text-color` | Point, LineString, Polygon | string | `#222222` |
| `text-halo-color` | Point, LineString, Polygon | string | `#ffffff` |
| `text-halo-enabled` | Point, LineString, Polygon | boolean | `true` |
| `text-halo-width` | Point, LineString, Polygon | number | `1.5` |
| `text-maxzoom` | Point, LineString, Polygon | number | `24` |
| `text-minzoom` | Point, LineString, Polygon | number | `0` |
| `text-size` | Point, LineString, Polygon | number | `12` |
| `tile_url` | VectorTile | string | ソースから自動抽出 |
| `vt-circle-color` | VectorTile(Point) | string | `#e63946` |
| `vt-circle-radius` | VectorTile(Point) | number | `6` |
| `vt-circle-stroke` | VectorTile(Point) | string | `#ffffff` |
| `vt-color-rule-enabled` | Point, LineString, Polygon, VectorTile | boolean | `false` |
| `vt-color-rule-field` | Point, LineString, Polygon, VectorTile | string | `""` |
| `vt-color-rules` | Point, LineString, Polygon, VectorTile | array | `[]` |
| `vt-geom-type` | VectorTile | string | `Polygon` |
| `vt-label-color` | VectorTile | string | `#222222` |
| `vt-label-enabled` | VectorTile | boolean | `false` |
| `vt-label-field` | VectorTile | string | `""` |
| `vt-label-halo` | VectorTile | boolean | `true` |
| `vt-label-halo-color` | VectorTile | string | `#ffffff` |
| `vt-label-maxzoom` | VectorTile | number | `24` |
| `vt-label-minzoom` | VectorTile | number | `0` |
| `vt-label-size` | VectorTile | number | `12` |
| `vt-line-color` | VectorTile(LineString) | string | `#1d6fa4` |
| `vt-line-dasharray` | VectorTile(LineString) | array | `[]` |
| `vt-line-opacity` | VectorTile(LineString) | number | `1.0` |
| `vt-line-width` | VectorTile(LineString) | number | `2.0` |
| `vt-outline-color` | VectorTile(Polygon) | string | `#ffffff` |
| `vt-outline-dasharray` | VectorTile(Polygon) | array | `[]` |
| `vt-outline-width` | VectorTile(Polygon) | number | `1.0` |
| `vt-source` | VectorTile | string | `""` |
| `vt-source-layer` | VectorTile | string | `""`（**実質必須**） |
| `vt-tree-svg-enabled` | VectorTile(Point) | boolean | `false` |

### 同名キーの意味がジオメトリで変わるもの

| キー | Polygon での意味 | LineString での意味 |
| --- | --- | --- |
| `line-width` | 外周線の幅（UIなし・既定 1.0） | 線本体の幅（UIあり・既定 2.0） |
| `line-opacity` | 外周線の不透明度 | 線本体の不透明度 |
| `line-dasharray` | 外周線の破線パターン | 線本体の破線パターン |

---

## 付録B: 既知の注意点・落とし穴

| # | 事象 | 内容 |
| --- | --- | --- |
| 1 | **`num_max` は描画に効かない** | 数値モードの区間上限は「次の行の `num_min`」で決まる。`num_max` は凡例ラベル専用。隙間を空けて書くと前の区間の色が伸びる |
| 2 | **`num_max` だけの行は描画されない** | `num_min` を持たない行は `step` 式から除外される。凡例には出るため、凡例と地図が食い違う |
| 3 | **数値モードは `num_min` 昇順にソートされる** | ファイル上の並び順は描画に影響しない。一方で凡例はファイル順のまま。並びを揃えるには最初から昇順で書く |
| 4 | **文字列ルールと数値ルールは混在できない** | どちらか1つでも `num_min`/`num_max` があれば配列全体が数値モードになる |
| 5 | **`text-halo-enabled` は fgb ベクタでは出力に反映されない** | `false` にしても `text-halo-color` / `text-halo-width` がそのまま `paint` に出る。縁取りを消すには `text-halo-width` を `0` にする。VectorTile 側（`vt-label-halo`）は正しく無効化される |
| 6 | **VectorTile ラベルの縁取り幅は 1.5 固定** | 対応キーが存在しない |
| 7 | **`circle-radius` / `vt-circle-radius` は色分けできない** | 半径は常に単一値。属性に応じて大きさを変えられるのは単木SVG（`vt-tree-svg-enabled`）のみ |
| 8 | **点の不透明度に UI がない** | 既定 `1.0` はコード側にハードコード。色分けルールの `opacity` か `rgba()` 表記の色で対応する |
| 9 | **Polygon の外周線幅 `line-width` に UI がない** | ただし `.fgstyle` の値は**「適用」を跨いでも失われない**。`_apply_style_to_layer()` は Polygon に対して `line-width` を書かないため、読み込んだ値がそのまま `_build_html()` へ渡る。したがって QML からの変換では `.fgstyle` に書くだけで枠幅が反映され、本体の改修は不要（[7章](#7-面polygon)） |
| 10 | **`vt-source-layer` が空だと HTML 出力が失敗する** | `ValueError: VectorTileのsource-layerが未指定` |
| 11 | **`tile_url` は読込で上書きされない** | 現在のレイヤの値が保持されるため、URL の移行には使えない |
| 12 | **色が空のルール行は保存されない** | UI で色未設定のまま保存すると、その行は消える |
| 13 | **`vt-tree-svg-enabled` は色分けより優先** | 単木SVG 有効時、フォールバックの円は黒固定になる |
| 13b | **属性値の型ゆれは入力側で吸収する** | MapLibre の `match` / `step` / 比較演算子はいずれも型に厳密で、FlatGeobuf・MVT 側の型（数値かテキストか）は QGIS のプロジェクト定義からは確定できない。そこで**入力式で型を揃える**のが唯一の確実な方法: 文字列ルールは `["to-string", ["coalesce", ["get", f], ""]]`、数値ルールは `["to-number", ["coalesce", ["get", f], -1000000000], -1000000000]`。型セーフ版の本体（`_rule_input_expr()` を持つもの）はこれを自動で行う |
| 13c | **型不一致は3通りの壊れ方をする** | 同じ型不一致でも症状が違うので混同しないこと。**`match`**（色分け）→ どのルールにも一致せず既定色。**`step`**（数値色分け）→ 実行時エラーになり、そのプロパティが MapLibre の**仕様既定値**へ落ちる（`line-width: 1` / `line-opacity: 1` / `line-color: #000000` ＝「なぜか全部同じ黒い細線」になる）。**`filter`**（破線の分割）→ 実行時エラーは `false` 扱いなので**地物が丸ごと消える**。色分けは効かないのに線は見えている、という状態から破線対応を入れた途端に全部消えるのはこのため |
| 13d | **既定不透明度0＋型不一致で全消え** | 「該当なしを透明にする」ために既定の `fill-opacity` / `line-opacity` を0にしたスタイルで 13b が起きると、どのルールにも一致せずレイヤ全体が不可視になる |
| 14 | **読込は「プリセット」であり確定ではない** | 「このレイヤにスタイルを適用」を押さないと反映されない |
| 15 | **`_version` は検証されない** | 未来のバージョンのファイルもエラーなく読める。互換性は書き手側で担保する必要がある |
| 16 | **式を含むスタイルはUIプリセットで落ちる** | `_on_layer_selected()` が `int(style.get("circle-radius"))` などを行うため、値がリストだと `TypeError`。[15.3](#153-制約) 参照 |
| 17 | **式を含むスタイルは「適用」で消える** | `_apply_style_to_layer()` がUIの値で上書きするため、式を保持するには退避・復元が必要 |
| 18 | **判定値の全角・前後空白は一致しない** | `match` は完全一致。全角数字（`１２３`）・全角空白・前後の空白はデータ側の表記と食い違うと無視される。同じ色の別名ルールを併記すれば両方に当てられる（`fgstyle Maker` は自動で行う） |
| 18b | **判定値の重複は先勝ち** | 同じ `value` のルールが複数あると、`match` 式では先に並んだ方だけが有効。後続は凡例に出るだけで描画に効かない |
| 19 | **太さ・サイズの単位はCSSピクセル** | `.fgstyle` のキーに単位表記は無いが、`_build_html()` が `paint`/`layout` へ素通しするため MapLibre の CSS ピクセルとして解釈される。QGISの mm/pt 指定は換算が必要（1mm = dpi/25.4 px、1pt = dpi/72 px） |
| 19b | **`line-dasharray` はデータ駆動式にできない** | MapLibre の制約（ズーム関数のみ）。区分ごとに破線を変える場合は `vt-color-rules[].dasharray` を使い、本体側が `filter` 付きレイヤへ分割する |
| 19c | **`line-dasharray` の単位は線幅の倍数** | ピクセルではない。線幅を変えると破線の見た目も比例して変わる。`line-width` を後から変えたら `line-dasharray` も組み直す必要がある（実寸 = 倍数 × 線幅） |
| 19f | **隙間が2px未満の破線は実線に見える** | MapLibre は線の縁を必ずアンチエイリアスし、これは破線の切れ目にも及ぶため、隙間が 2px 程度を下回ると両側のにじみが重なって切れ目が消える。QGIS（Qt）は切れ目を鋭く描くので、**同じ数値でも QGIS では点線・WEBでは実線に見える**。対処は隙間側の倍数を上げる（線分は変えなくてよい）。例: 線幅1.2px で `[3.75, 1.25]`（隙間1.5px）→ `[3.75, 1.667]`（隙間2.0px）。`fgstyle Maker` は「破線の最小隙間」で自動調整する |
| 19d | **凡例名は列6が空だと判定値がそのまま出る** | 数値で色分けすると凡例が `619～620` のような数値幅になる。QGIS の凡例名（`K21_vas_ap` 等）を出したい場合は `vt-color-rules[].label`（UI 列6）を使う。`fgstyle Maker` は QML の `label` を自動で入れる |
| 19e | **旧版本体で開くと `label` / `dasharray` が落ちる** | 6列の `tblVtColorRules` を持つ版では列6・列7が無いため、「適用」を押した時点でこの2キーが失われる（読み込み直後の HTML 出力までは効く） |
| 20 | **サブピクセル幅の線はほぼ見えない** | QGISはヘアラインとして描くが MapLibre は指定どおり細く描く。`line-width: 0.4` は実用上不可視。1.0px 程度が下限 |
