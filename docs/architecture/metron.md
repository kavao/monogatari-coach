# METRON 技術詳細

## TL;DR

METRON は、Scene を Beat に分けて本文の密度と構造予算を計測し、必要な Beat だけを局所修復する検査レイヤです。V0 はマーカー付き本文の計測とレポート、V1 は承認済みモデル設定に基づく失敗分類・生成単位計画・Expand を扱います。外部 provider への接続はこのモジュールの責務ではありません。

## 保存単位

Scene ごとの成果物は、本文アンカーと同じ `scene_id` を使って次へ保存します。

```text
novels/<作品>/_metron/<scene_id>/
  contract.yaml
  beats.yaml
  draft.NNN.md
  spans.NNN.yaml
  metrics.NNN.yaml
  regression.NNN.yaml
  report.NNN.md
  FINAL.md
config/metron_models.yaml
```

`SceneContract`、`BeatPlan`、`Spans`、`Metrics` は Pydantic v2 のモデルを実行時の正とし、YAML は保存形式として扱います。`scene.id` は `chNN-MMM` 形式で、`_metron/<scene_id>/` と一致させます。V0 では `chronos_span` を省略できます。

## 作品単位の有効化

作品ごとに METRON の自動ワークフローを使う場合は、作品の `config.md` の「## 基本情報」表に次の行を追加します。

```markdown
| METRON | ON |
```

新規作品の初回作成は `python tools/novel_onboard.py` を入口にします。作成時に確認への返答がない場合は「未応答・既定 ON」として行を記録し、`_metron/` を作ります。OFF はユーザーが明示したときだけです。既存作品の行なしも従来どおり OFF です。明示 OFF した作品をあとから ON にしたときの後追い計測と、計測が古い章の扱いは [Writing bridge](writing-bridge.md#off-で下書きしあとで-on-にして洗練する) を参照してください。

行なしまたは `OFF` なら、自動ワークフローは METRON の成果物作成・計測を行いません。`ON` でも本文保存の完了ゲートにはならず、契約・Beat・マーカー不足や CLI 失敗は `未計測／要対応` として本文保存と分けて報告します。`novel_project_check.py --check-inspection-layers` は、`_metron/` が空の場合と、本文がある章に対応する契約・Beat・run が欠けている場合を WARN として列挙します（終了コード 0）。明示的に `metron_cli.py` を実行した場合は、このフラグを理由に拒否しません。

フラグの値は `ON` / `OFF` のみです。未知値・重複キー・既存 `config.md` の読込失敗は設定エラーとして扱います。V1 の Deepen / 再生成や provider 呼び出しは、承認済み設定とユーザー承認が別途必要です。執筆工程への接続は [Writing bridge の局所修復と本文反映](writing-bridge.md) です。`chronos check` や `metron_cli.py analyze` を同じ本文版へ重ねません。

## 計測と判定

本文は NFC に正規化し、Beat マーカーを除去した本文上のコードポイント半開区間として `spans` に記録します。`Beat coverage` は BeatPlan の全 ID に正しい開閉マーカーのスパンが 1 件ずつある状態です。

`scene.overall_budget_ratio` は `scene.chars / Σ(beat.chars_hint)` です。`head_tail_ratio` は先頭 2 Beat と末尾 2 Beat の密度比で、4 Beat 未満または先頭群ゼロの場合は算出しません。

V1 の自動修復候補は次のクラスです。

- `BeatMissing`: マーカー・スパンの欠落、またはモデル別のスパン下限未達（単独再生成。極端な短さだけ）
- `BeatThin`: 段落数・会話往復数と、段落・会話充足率の構造予算未達。計画下限未達だけ Deepen します。校正典型値だけの未達は指摘を残し、自動修復しません。文字数比とは別統計です
- `TooShort`: シーンが `chars_floor` 未満、または Beat が `chars_hint` 未満（Deepen のみ。末尾再生成には使わない）
- `EndingRush`: 末尾密度比のモデル別閾値未達（末尾 Beat の単独再生成）

分量バーは構造バーと別に置きます。シーンの床は `generation.chars_floor`（既定 4000字）、Beat の床は `chars_hint` です。未達は `TooShort` になり、出来事を変えずにニュアンスを深める Deepen だけで自動修復します。末尾の再生成には使いません。Writer / Deepen への字数指示は床以上の指示目標です（既定 1.4 倍。シーン床 4000 字なら 5600 字。床 1 字では丸めで 1 字のままです）。水増しは禁止します。深化の対象は、既にある出来事の解像度（動作の分解・感覚・心理の迷いと判断・相手の反応・その人物らしい癖）と、感情の変化と身体の変化、会話です。新しい出来事・選択・事実は足さず、Deepen の指示には新規事実の件数も出しません。すでに書いた内容の言い換えは対象にしません。執筆接続の `context.md` は、この下限と指示目標を人間が読める形で出します。指示目標は助言であり、未達だけでは検査を止めません。既存の作業 run は新しい `prepare` が必要です。

`GenerationTruncated` は従来どおり自動修復しません。欠落Beatがあっても `regenerate` や Deepen へ進めません。感覚描写・内面描写・要約標識は補助指標であり、V1 の `BeatThin` の単独根拠にはしません。減衰キャリブレーションの `too_short_ratio` はシーン合格線に使いません。

## V1 の修復境界

`classify.py` は `config/metron_models.yaml` の `calibrated: true` かつ必要な値が揃ったモデル設定だけを受け入れます。`granularity: auto` は Beat の `chars_hint` 合計が `reliable_span_chars` を超えた場合に Beat 単位へ切り替えます。`isolated`、heavy Beat、末尾 hook は独立コールとして計画します。

provider 呼び出しは `repair_scene()` のコールバックへ注入します。Expand は同一 Beat につき最大 2 回で、`expand_retention_threshold` 未満の元文残存率、元本文と同一の候補、文字数が増えていない候補、新規文が既存文または同一候補内の他の新規文と高類似の候補は棄却して著者提示へエスカレーションします。類似度は句読点を除いた文字 2-gram の Jaccard で、短い反応文は対象外です。結合校正は最大 1 回で、短縮・元文の文の削除・Beat 順の入れ替え・事象変更を許容しません。Beat マーカーを保持して校正し、同一の冒頭文が新たに反復された場合も機械的に棄却します。再計測は正規化済みの最終本文と一致するマーカー付き稿で行います。シーンが `chars_floor` 未満のときは、必須の下限未達を先に直し、追加候補だけ飽和していない Beat へ寄せます。適格が無く必須修復も無いときは結合校正も出さず、`__scene_floor__` で止めます。`FINAL.md` へ保存する本文からは Beat / fact コメントを除去し、連続した空行は場面転換用の1行までに正規化します。既存の `FINAL.md` は上書きしません。

## 規定量調整

既にある本文を目標字数へ伸縮する作業です。V1 の修復と同じ再生（replay）型のセッションで動き、writing_bridge の `repair-begin --intent length` から始めます。手順とコマンドは [Writing bridge の規定量調整](writing-bridge.md#規定量調整既にある本文を目標字数に合わせる)、技法の基準は `_how_to.example/length_ops.md` です。

- **許容帯**: `LengthTarget`（`target_chars`、`tolerance.lower` / `upper`。既定 0.97 / 1.03、`scope` は `scene` か `beat`、`max_passes` 既定 3）。下限は切り上げ、上限は切り捨てで字数にします。上限が床（場面は `chars_floor`、Beat は `chars_hint`）より小さい設定は受け付けません。実効の下限は許容帯の下限と床の大きい方で、床で引き上げたときは `LENGTH_LOWER_RAISED` を残します。`chapter` は受け付けません。
- **一方向の伸縮**: 下限に足りなければ `deepen`、上限を超えていれば `tighten` だけを出します。増量は重みの重い Beat、計画に対して薄い Beat の順に配ります。増量で上限を超えたときだけ `tighten` で戻し、減量からは増量へ戻りません。同じ Beat への同じ操作は2回まで、全体は `max_passes` 回までで、棄却・却下された候補も数えます。
- **引き締め候補の検査**: 字数が減ること、Beat が元の半分より短くならないこと、実効の下限と場面の床を割らないこと、各文の文字が元文のどれかの文へ順序どおり 6 割以上含まれること（新しい文の検出）、文の順序が変わらないことを確かめます。出来事の一部が消えた候補はこの検査では見分けられないため、採用には著者の確認を要します。
- **場面単位の語句反復（Deepen 全般）**: 新しい文が持ち込んだ10字の語句が、場面全体（全 Beat）で3回目以上になる候補は `phrase repeats across the scene` で棄却します。新しい文が他の Beat の文の言い換えなら `new sentence paraphrases another beat` で棄却します。語句は文の中だけで数え、文の境目をまたぎません。意図した反復は `contract.yaml` の `scene.allowed_repeats` に書いた語句だけ許します。Deepen の指示には、場面内ですでに2回以上使われた語句（繰り返さない語句）と、禁止の型（修飾句の連打、葛藤のやり直し、数値での計測、Beat 末尾の定型の情景）を載せます。閾値は 043 第2章の3稿（10字の語句で場面内3回以上: 調整前 1種 → Deepen 後 34種 → 清書後 7種）で決めました（`metron/repetition.py`）。
- **仕上がり目標**: `LengthTarget.finish_chars` に清書後の仕上がり目標を持ちます。`finish_target()` は、それに余地（既定 +8%、`DEFAULT_FINISH_MARGIN`）を足した字数を増量の目標にします。仕上がりの帯は `finish_bounds()`（下限は床まで引き上げ）です。仕上がり目標が床と両立しない設定（例: 仕上がり190字・床200字）は、増量の目標が余地で床を超えていても、開始前に `LENGTH_CONFIG` で拒否します。場面単位の反復で、ずれて重なる10字の語句をつなぐときは、つないだ語句が同じ文の中に実在するときだけ伸ばします。前後の稿での回数も、構成する短い語句の回数からは推し量らず、つないだ語句そのものを含む文の数で数えます。
- **増量候補の検査**: 通常の Deepen と同じ検査（元文残存率・同義反復・場面単位の反復）に加え、指示に既出事実リスト（調整前の本文と、当該場面の CHRONOS イベント）を渡し、新しい出来事・人物・過去・選択・所持品を足さないよう指示します。
- **欠落 Beat**: 開始時に `BeatMissing` があれば、分量の調整に入る前に再生成で埋めます（`max_passes` には数えません）。再生成のあとで分類をやり直し、まだ欠落に当たる Beat が残る場合も含めて、埋められなければ `LENGTH_REQUIRED_UNREPAIRED` で止め、分量は合わせません。打切り（`GenerationTruncated`）や Beat 境界の異常は従来どおり開始しません。
- **終了**: 許容帯に入り、場面の床も満たせば `LENGTH_IN_BAND` で完了します。届かなければ `__length__` で止め、`LENGTH_MAX_PASSES`、`LENGTH_ESCALATE_ADD`（加筆の候補 Beat を添える）、`LENGTH_ESCALATE_REVISE` を残します。Beat 指定で Beat は帯に入っても場面が床に届かないときは `LENGTH_SCENE_FLOOR`、対象の Beat が `expandable: false` のときは `LENGTH_NO_ELIGIBLE` で止めます。`repair-finish` で途中終了したときも、許容帯に入っていなければ `escalated`（`LENGTH_NOT_IN_BAND`）です。同じ `repair-submit` の再送は、提出済みの同一結果として扱います。
- **収束（減量）**: 引き締めで上限に届かないときだけ、作者が `_metron/<scene_id>/episodes.yaml` に登録した子エピソードを要約へ畳みます（`condense`。1件につき1回）。畳む順は、持ち帰り（`carry_back`）も局所的効果（`local_payoff`）も無い子、局所的効果だけの子、持ち帰りの少ない子の順です。指示には残すべき持ち帰りと状態変化を載せます。候補は子エピソードの範囲だけを置き換え、短くなっていること、実効の下限と場面の床を割らないことを確かめます。範囲の引用が見つからない子は `CONDENSE_SKIPPED` で飛ばします。増量で上限を超えたあとは収束せず、引き締めだけを使います。
- **CANON 検査**: `metron/canon_check.py` が検査用の指示と、返ってきた JSON の判定を受け持ちます。provider は呼びません。追加（OP-E）と変更（OP-W）は常に不合格です。欠落は、収束の要約で覆われ、状態変化・持ち帰り・感情の向き（CHK-C1〜C3）が保たれているときだけ認めます。検査は事実を一文ずつ挙げさせ（`facts_before` / `facts_after`）、記録に残します。
- **子エピソード契約**: `metron/episodes.py`。書式は `_how_to.example/length_ops.md` の子エピソード契約に `beat_id` と `span`（開始・終了の引用）を足したものです。加筆で子エピソードを足すときの必須条件は `addition_issues()` で確かめられます。本文を書く前に設計から登録した子は `span_pending: true` とし（`span` と同時には書けません）、範囲が決まるまで収束・脱落の対象から外します（`CONDENSE_SKIPPED`）。`span` を省いた子（Beat 全体）とは別です。
- **不足率と設計追加（D21）**: `metron/length.py` の `shortage_ratio(T, C)` は `max(0, T − C) / T`、上限は `DESIGN_SHORTAGE_LIMIT`（0.10）です。Deepen は上限未満の不足だけに使い、それ以上は出来事を足す設計追加へ回します。判定と記録は writing_bridge が行います（[Writing bridge の規定量調整](writing-bridge.md#規定量調整既にある本文を目標字数に合わせる)）。

収束対象がある減量では、`max_passes` が2以上のときに収束用の1回を残します。既定3回なら、引き締めを最大2回試してから収束へ移ります。上限1回は引き締めだけを試し、増量後に上限を超えた場合は従来どおり引き締めだけを行います。

CANON 検査結果には `completed: true`、指示に記載された `input_sha256`、空でない事実一覧、指摘一覧が必要です。未完了や欠落項目を合格扱いにしません。writing_bridge が検査依頼時の入力を保存し、結果の入力ハッシュと照合します。本文・候補・イベントなどが変わった場合は、同じジョブでも検査をやり直します。

### 床到達後の EndingRush と契約修正

通常の修復（auto）で、開始時は床に届かず途中の Deepen で床を超えた場合、開始時に予定した末尾の再生成は行わず、`ENDING_RUSH_ADVISORY` として報告に残します。末尾の再生成は章末の状態を変えやすく、契約からずれる原因になるためです。`explicit_deepen` で明示した場合は従来どおり再生成します。

章末などを契約・設計に合わせて書き直すときは、契約修正（`metron/contract_fix.py`、writing_bridge の `--intent contract_fix`）を使います。指定 Beat を指示どおりに再生成し、長さは旧稿ではなく Beat の床（`chars_hint`）で判定します。棄却されても同じ Beat に2回まで候補を出せます。届かなければ `CONTRACT_FIX_NOT_ACCEPTED` で止めます。Beat の床を満たしても場面全体が床を割るときは、候補を残したまま `CONTRACT_FIX_SCENE_FLOOR` で `escalated` にします。打切り（`GenerationTruncated`）の稿や、書き直す Beat 以外の欠落がある稿では、契約修正を始めません。

## 開発上の入口

正規の実行入口は `python tools/metron_cli.py` です。CLI は契約検証、計測、レポート、ローカル fixture のキャリブレーション集計、V1 判定、生成コール計画、マーカー除去済み FINAL 保存を提供します。実測生成や provider の認証情報は CLI の暗黙動作にしません。
