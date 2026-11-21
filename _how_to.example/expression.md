# expression — 表現ミックス（文章のウェイト）

通常小説の本文で、何を厚く書くかの相対重み。成熟の構文軸（O1〜O10）とは別である。

- **既定では読まない。** `_meta.md` の「表現ミックス」節の **状態が ON** のとき、または作者がミックスの指定を求めたときだけ読む。
- 作品の決定の正本は、作品 `_meta.md` の「表現ミックス」節である。機械が読む初期設定は **状態: ON / OFF**（新規の既定は OFF。節が無ければ OFF）。この葉の改訂で既存作品は書き換えない。検証は `tools/novel_expression_mix.py … validate`。
- 重みの数値は YAML（`expression/catalog.yaml`・`default.yaml`・`profiles/`）。手順はスキル **`novel-planning`**。

## 1. 何を扱うか

見せ方軸は、内心をどこまで語るか、価値を誰が判定するかといった**経路**である。表現ミックスは、同じ出来事の本文で**どの種類の文を厚くするか**である。

優先は「設定と筋 ＞ 見せ方軸 ＞ 表現ミックス ＞ `writer_profile.md` ＞ `novelcore.md`」。見せ方軸の INTERIORITY が低い作品では、内面の重みを上げても独白を増やさない。

完了ゲートにしない。句読点ゲートや METRON の床とは別である。

## 2. 核カテゴリ

ID の定義と METRON への写し先は [`expression/catalog.yaml`](expression/catalog.yaml)。新しい技法本文はここに書かない。

| ID | 厚くするもの | 写し先 |
|---|---|---|
| `action` | 動作の分解 | `type: action` |
| `sensory` | 五感 | `budget.sensory` |
| `interiority` | 内面 | `budget.interiority`（見せ方軸で上限） |
| `dialogue` | 会話往復 | `type: dialogue`、`dialogue_turns` |
| `gesture` | 所作・身体言語 | 会話を増やさず `type: action` |
| `sound` | 現場音 | `budget.sensory`（独立 Beat にしない） |
| `environment` | 情景 | `budget.sensory` |
| `process` | 時間の伸び・手順 | `chars_hint` / `paragraphs` |
| `daily` | 生活行動 | `type: action` |
| `metaphor` | 比喩 | 写さない。崩れる文は書かない |

接触音など成熟専用のカテゴリは核に入れない。作業用 `catalog.yaml` で足し、そのプロファイルだけ重みを上げる。

## 3. 重みの解決

後勝ち。ファイルは合成しない。作業用 `_how_to/expression/` に同名があれば、その1ファイルだけを使う。

1. 標準 `default.yaml`
2. ジャンル軸の `profiles/<genre_id>.yaml`（複数なら ID 順。衝突は作者へ一言）
3. 作品 `_meta.md` の凍結値（**状態: ON** のとき起草に使う。OFF・節なしは使わない）
4. 見せ方軸で内面の上限を切る

CLI: `uv run python tools/novel_expression_mix.py novels/<作品> resolve`  
検証: `uv run python tools/novel_expression_mix.py novels/<作品> validate`（状態は ON か OFF）

## 4. beats.yaml への写し

新しい YAML 方言を作らない。**状態が ON** のとき、新規の `beats.yaml` を書くときだけ、既存欄へ既定を出す。OFF と既にある beats は自動で書き換えない。

## 5. 独自ジャンル

公式カタログへ上げなくてよい。手順は [`genre/README.md`](genre/README.md)「表現ミックスと独自ジャンル」。

## 6. 起草への使い方

context_usage:
状態が ON のとき、実効の表現ミックス（作品の `_meta.md` の節）に従う。厚くする種類の文を先に書く。会話往復を増やして所作や現場音の代わりにしない。現場音の独立 Beat は置かない。比喩を厚くしても崩れる文は書かない。重み表はこの context に載せない。
