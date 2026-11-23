# expression — 表現ミックス（文章のウェイト）

通常小説の本文で、何を厚く書くかの相対重み。成熟の構文軸（O1〜O10）とは別である。

- **既定では読まない。** `_meta.md` の「表現ミックス」節の **状態が ON** のとき、または作者がミックスの指定を求めたときだけ読む。
- 作品の決定の正本は、作品 `_meta.md` の「表現ミックス」節である。機械が読む初期設定は **状態: ON / OFF**（新規の既定は ON。OFF は作者が明示したときだけ。節が無ければ OFF）。この葉の改訂で既存作品は書き換えない。検証は `tools/novel_expression_mix.py … validate`。
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

## 7. 清書・深化での使い方

状態が ON の作品で本文を直すときだけ使う。どこを直すか（要約で流した山場・相手の反応が無い会話など）と分量の判定には使わず、どの種類の文で足すか・どれから削るかだけに使う。手順の正本は `workflow-specification.md`「文章の伸縮（清書・規定量調整）の詳細」。状態が ON なら、明示の Deepen と規定量調整のジョブには、帯の高い種類と低い種類が口語で渡る（重み表は渡さない）。下の棄却条件のうち機械で見るのは会話の往復の上限だけで、ほかは作業者が確かめる。

| 深化で書き足すもの | 対応するカテゴリ |
|---|---|
| 動作の分解 | `action`・`gesture` |
| 感覚 | `sensory`・`sound`・`environment` |
| 相手の反応 | `gesture`・`dialogue` |
| 会話 | `dialogue` |
| 心の揺れ | `interiority`（見せ方軸の INTERIORITY が低ければ使わない） |
| 時間の伸び・生活 | `process`・`daily` |

- **全体の深化**: 深める箇所ごとに、帯の高い種類から書き足す。帯の低い種類では足さない。帯が中の種類は、その場面に要るなら足してよい。相手の反応と人物の迷いは、帯の高い種類の文で置き換えない（見せ方軸で内面を厚くする作品では、内面は中でも削らない）。`metaphor` は帯が高くても増量の手段にしない（言い換えの範囲だけ）。
- **引き締め清書**: 同じくらい冗長な候補なら、帯の低い種類の文から削る。帯の高い種類の文は、重複でなければ冗長として削らない。
- **採らない書き足し**: その Beat の `dialogue_turns` の上限を超える会話、現場音だけの新しい段落、INTERIORITY が低い作品の独白。
- 完了報告には、増やした種類を口語で書く（「所作と現場音を足した」）。カテゴリ ID は書かない。
