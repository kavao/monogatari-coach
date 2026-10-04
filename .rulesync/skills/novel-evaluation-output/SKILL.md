---
name: novel-evaluation-output
description: >-
  Editor Score・Consistency Audit（design / text）・Synopsis の評価結果を novels/.../_reader/ に保存し、
  チャットには要約だけを返す。novel-reader-output（足切り）とは別スキルとして分離し、
  保存先ファイル名・前処理手順・設定鮮度チェック・完了条件を固定する。
  Consistency Audit は足切りを前提にしない。
targets: ["*"]
---

## 目的

First Reader（足切り）通過後の深掘り評価モード（Editor Score / Synopsis）と、足切りを前提にしない Consistency Audit（`design` / `text`）で、評価結果の所在を曖昧にしない。

横断正本は **`.rulesync/rules/workflow-specification.md`** の「評価ファイル命名と役割」および「足切りと深掘り評価の住み分け」。このスキルは、それらの保存条件を満たすための実行手順を定める。

**重要**: 足切り（First Reader）は `.rulesync/skills/novel-reader-output/SKILL.md` が正とする。本スキルは足切り手順を上書きしない。

## 創作技法契約

既定は **評価は契約外**。工程正本（`editor_score.md` / `consistency_audit.md` / `novel_synopsis_for_review.md`）は selected に無くても読む。ユーザーが契約に照らすと明示したときだけ再読する。`pack_id` があるときは先に `novel_howto_contract_check.py --strict`。終了コード 0 以外は評価を始めず未完了。0 のときだけ `--json` の `present` を再読する。完了報告に「評価は契約外（工程正本のみ）」または再読した葉の拠り所1句を書く。

## 保存先（必須）

| 種別 | 参照する技法 | 保存先 |
|------|--------------|--------|
| Editor Score | `_how_to/editor_score.md` | `novels/<作品>/_reader/score_YYYYMMDD_HHMM.md` |
| Consistency Audit | `_how_to/consistency_audit.md` | `novels/<作品>/_reader/consistency_<scope>_YYYYMMDD_HHMM.md`（`<scope>` は `design` / `text`） |
| Synopsis（前処理） | `_how_to/novel_synopsis_for_review.md` | `novels/<作品>/_reader/synopsis_YYYYMMDD.md` |

- `_reader/` が無ければ作成する。
- 日付だけの旧 `consistency_YYYYMMDD.md` は読み取りだけ互換とし、上書きしない。scope が分からないので鮮度チェックの基準にしない。
- チャット欄に本文を書いただけでは完了ではない。評価本文は必ず上記ファイルへ保存する。
- 保存したファイルパスをチャットで明示してから完了扱いにする。

## 評価前チェックリスト（Editor Score / Synopsis）

Editor Score と Synopsis では、評価を開始する前に次の順序で確認する。Consistency Audit は「Consistency Audit の手順」に従い、足切りを確認しない。

1. **足切り済みであること**を確認する（`_reader/YYYYMMDD_HHMM.md` の判定が「読むべき」）。
2. `config.md` を Read し、作品名・ジャンル・ターゲット層を確認する。
3. 対象 `_novel_text/*.md` を Read する。
4. Editor Score では「評価前の設定鮮度チェック」を行ってから、`character.md` / `world.md` / `design_specification.md` を Read する。
5. `python tools/novel_char_count.py novels/<作品>` を実行し、対象範囲の文字数を取得する。
6. **長文チェック**: 合計30,000字超 or 章単体8,000字超の場合 → Synopsis 先行を推奨（詳細は「長文対応」節）。

## 評価前の設定鮮度チェック（Editor Score / text 監査）

設定3点を判断の基準に使う評価（Editor Score と Consistency Audit の `text`）だけで行う。First Reader / Interest Check / Reader Walk / Consistency Audit の `design` では行わない。

1. `python tools/novel_audit_freshness.py check novels/<作品>` を実行する。判定はこのツールの終了コードを正とし、ハッシュを目で比べない。
2. 終了コード 0（監査済み）なら、そのまま依頼された評価へ進む。
3. 終了コード 1（未監査: 設定監査が無い、または最新の設定監査以降に設定3点が変わった）なら、依頼された評価の前に `design` 監査を1回実行する（`起動: pre_review`）。手順は「Consistency Audit の手順」の design と同じで、**指摘は直さない**。保存と `_meta.md` 追記まで済ませてから、依頼された評価へ戻る。設定監査で矛盾が出ても、依頼された評価は止めない。
4. 終了コード 2（作品フォルダや設定3点が無い）なら、鮮度チェックは「不可」として理由を完了報告に書き、依頼された評価は続ける。
5. pre_review を実行したときは、依頼された評価の完了報告の **先頭に別の節**として、設定監査の保存先・件数・矛盾と要確認の一覧を書く。評価本体の結果と混ぜない。

## Editor Score の手順

1. 評価前チェックリスト（鮮度チェックを含む）を実施する。
2. `_how_to/editor_score.md` を Read する。
3. 5項目100点満点で採点し、致命的弱点・改善候補・設計との乖離を明示する。
4. 結果を `_reader/score_YYYYMMDD_HHMM.md` に保存する。
5. 作品 `_meta.md` の「評価・足切り履歴」節に Editor Score のパスと点数を追記する。

チャットへは「総合点・致命的弱点の件数・保存先パス」と契約の扱い（契約外または再読した葉）を返す。

## Consistency Audit の手順

足切り（First Reader）の結果を前提にしない。点数は付けない。執筆完了・publish の条件にしない。判定の境界（矛盾 / 要確認 / 軽微）の短い正本は `workflow-specification.md` の「Consistency Audit Mode」。

### scope の決定

| 依頼・起動 | scope |
|------------|-------|
| 「設定（資料）の一貫性を監査して」 | `design` |
| 「本文の一貫性を監査して」「第1〜3章の一貫性を監査して」 | `text` |
| 「一貫性を監査して」（指定なし） | 本文が1章以上あれば `text`、なければ `design`。完了報告の先頭に、どちらにしたかを書く |
| 企画の Gate B（スキル **`novel-planning`** の B4.5） | `design`（`起動: gate_b`） |
| 評価前の設定鮮度チェックで未監査 | `design`（`起動: pre_review`） |

### 共通

1. `_how_to/consistency_audit.md`（無ければ `_how_to.example/consistency_audit.md`）を Read する。
2. `character.md` / `world.md` / `design_specification.md` を Read で読み直す。書いたときの記憶ではなく、ファイルの内容を入力にする。
3. 任意: `python tools/novel_proper_noun_lint.py novels/<作品>` を実行してよい。見出し・Mermaid・読み付き・姓名の分かちだけを照合する。終了コード 1 でも監査は止めない。Gate A の必須にはしない。
4. 指摘の表と **確認した組み合わせの一覧**（組み合わせごとの確認項目数と指摘数）を作る。件数0件でも書く。一覧が無い監査は未完了とする。
5. 各指摘には食い違う二つの記述の出典を両方書く。矛盾を要確認へ下げるときは、読み替えの余地を行に書く。
6. 保存名は `_reader/consistency_<scope>_YYYYMMDD_HHMM.md`。冒頭に種別・scope・起動・日時・対象パス・CHRONOS 添付・件数を書く。ファイル名と冒頭の scope を一致させる。件数は記憶で書かず、指摘表の判定列を数えて書く。前回指摘の解消確認など件数に含めない表では、判定欄を「前回: 矛盾」のように書く。
7. 保存後に `python tools/novel_consistency_audit_lint.py <監査ファイル>` を実行する。終了コード 0 になるまで冒頭の件数・組み合わせ表を直す（指摘の判定は変えない）。終了コード 0 になる前に完了報告しない。
8. 作品 `_meta.md` の評価履歴表へ Audit 行を追記する（「`_meta.md` 更新」節）。件数は lint を通した冒頭の件数を写す。
9. 完了印の語は「監査済み」。「検査済み」「計測済み」（CHRONOS / METRON の語）は使わない。

### design

1. `_novel_text/`・足切りファイル・CHRONOS・METRON は読まない。CHRONOS 添付は常に `なし`。
2. Gate A 直後の薄い資料（章出来事が抽象的、人物に口調・目的が無い）なら「不可」として止め、理由を返す。
3. `python tools/novel_audit_freshness.py hash novels/<作品>` の出力（設定ハッシュ）を冒頭へそのまま貼る。
4. 指摘をもとに資料を直さない。例外は B4.5 で本文が無い場合だけで、その扱いはスキル **`novel-planning`** の B4.5 が正とする。冒頭に `本文なし・修正あり` / `本文あり・未修正` を書く。

### text

1. 本文が0章なら「不可」として止める。
2. 開始前に「評価前の設定鮮度チェック」を行う。
3. 指定範囲の `_novel_text/`（省略時は全章）を Read し、`python tools/novel_char_count.py` で文字数を取る。
4. 「本文と設定の照合」を書く。本文と設計書の照合は、対象章の確定出来事を番号ごとに本文と突き合わせ、照合した番号の範囲を組み合わせ表に書く（拾い読みで済ませない）。第2章以降があれば「章をまたぐ観点」も書く。第1章だけのときは章横断の節に「対象外（1章のみ）」と書く。
5. **CHRONOS 添付**: `config.md` が `CHRONOS | ON` で有効イベントがあるときだけ `python tools/chronos_cli.py check novels/<作品>` の結果を読み、時系列の節へ添付する。失敗しても監査は続ける。OFF または `chronos/` 無しは `なし`、イベント0件は `未登録`（矛盾にしない）。本文とイベントの前後が食い違うときは要確認とする。イベント YAML は書かない。`writing_bridge` / `metron_cli.py analyze` は呼ばない。
6. 本文も設定も直さない。

チャットへは「scope・起動・矛盾件数（矛盾/要確認/軽微の内訳）・保存先パス」と、要確認の一覧を返す。

## Synopsis の手順

1. `_how_to/novel_synopsis_for_review.md` を Read する。
2. 全文またはG3対象章を Read し、400字前後の客観的あらすじを作成する。
3. 結果を `_reader/synopsis_YYYYMMDD.md` に保存する。
4. その後、Editor Score または G3 足切りへ進む。

チャットへは「保存先パスと、次に何を実行するか」だけ返す。

## 長文多段パイプライン（合計30,000字超 / 章8,000字超）

横断正本は **`.rulesync/rules/workflow-specification.md`** の「評価作業一時領域（`_reader/_work/`）」および「長文評価の閾値と前処理」。

### 作業領域の構造

```
novels/<作品>/_reader/
  synopsis_YYYYMMDD.md          ← 最終成果物（Step A）
  _work/<YYYYMMDD>/             ← 評価セッション作業フォルダ
    ch01_eval.md                ← 章1 スコアノート
    ch02_eval.md
    ...
    chNN_eval.md
    step_b.md                   ← 構造・プロット中間分析
    step_c.md                   ← 文体・描写中間分析
    aggregate.md                ← 加重平均計算メモ
  score_YYYYMMDD_HHMM.md        ← 最終成果物（Step D）
```

### 手順

**Step 0: 入力収集**

1. `python tools/novel_char_count.py novels/<作品>` を実行し、章ごとの文字数と合計を取得する。
   - **注意**: 本スクリプトは `novel_text*.md` のみ計数する。`novel_prologue.md` 等はパターン外なので、存在する場合は別途 Read して文字数を推定し合計に加算するか、注記として aggregate.md に記録する。
2. `_novel_text/` 内のファイルリストと章構成（`01_1`, `01_2`…のグループ）を把握する。
   - **章グループ化ルール**: `novel_text01_*` を「第1章」としてグループ化する。`novel_prologue.md` は、3,000字未満の場合は第1章グループに合算してよい。3,000字以上は「プロローグ」として独立グループとする。
3. `config.md` / `character.md` / `world.md` / `design_specification.md` を Read する。
4. 前回の `_reader/` に評価ファイルが存在する場合、パスと判定を確認する。
   - **旧形式（5段階）の扱い**: 旧評価は変更せず残す。引用時は「旧形式(5段階 X.X/5.0 ≈換算 XX/100 相当・参考値)」と明示する。
5. 作業フォルダ `_reader/_work/<今日の YYYYMMDD>/` を作成する（`_reader/` が無ければ先に作成）。
   - Windows (PowerShell): `New-Item -ItemType Directory -Force "novels/<作品>/_reader/_work/<YYYYMMDD>"`

**Step A: Synopsis（前処理）**

1. `_how_to/novel_synopsis_for_review.md` に従い、全文から 400字前後の客観的あらすじを作成する。
2. `_reader/synopsis_YYYYMMDD.md` に保存する（最終成果物）。

**Step B: 構造・プロット・テーマ分析（あらすじから）**

1. Step A の Synopsis のみを入力として、物語構造・伏線・テーマ一貫性を分析する。
2. 分析結果を `_reader/_work/<YYYYMMDD>/step_b.md` に保存する（作業ファイル）。

**Step C: 文体・描写分析（章サンプルから）**

1. 序盤・中盤・終盤から代表章を1〜2章ずつ抜粋して Read する（全文一括が困難な場合）。
2. 語彙・リズム・描写密度・ジャンル適合を評価する。
3. 分析結果を `_reader/_work/<YYYYMMDD>/step_c.md` に保存する（作業ファイル）。

**Step D: 章分割スコア + 加重平均 → 統合**

1. 各章グループ（例: `novel_text01_*` をまとめて「第1章」）に対してスコアを付ける。
2. 各章スコアを `ch01_eval.md`〜`chNN_eval.md` に保存する（作業ファイル）。
3. `aggregate.md` に加重平均を記録する:
   ```
   最終総合点 = Σ(章スコア × 章文字数) ÷ 合計文字数
   ```
4. Step B・Step C・各章スコアを統合し、`_how_to/editor_score.md` の出力形式で `score_YYYYMMDD_HHMM.md` を作成する（最終成果物）。
   - **フロントマター要件**: `score_*.md` の冒頭には次を含める: 種別（Editor Score）・作品名・日時・対象範囲（章とファイル数と文字数）・ゲート前提（足切り済みの根拠）・算出根拠（長文時は `_reader/_work/<YYYYMMDD>/aggregate.md` のパス）。
5. 作品 `_meta.md` の「評価・足切り履歴」節を更新する。

チャットへは「Editor Score 総合点・致命的弱点の件数・`synopsis`・`score` の保存先パス」を返す。

### パイプライン完了の定義（長文）

以下が **全て** 揃ってから「Editor Score 完了」と報告する:

1. `_reader/_work/<YYYYMMDD>/` に `step_b.md` / `step_c.md` / 各 `ch*_eval.md` / `aggregate.md` が存在する
2. `_reader/synopsis_YYYYMMDD.md` が存在する
3. `_reader/score_YYYYMMDD_HHMM.md` が存在する（PowerShell の `Test-Path` または `Read` で確認）
4. 作品 `_meta.md` の「評価・足切り履歴」節を更新した

チャットに「保存した」と伝えてよいのは 3 を確認した後。

### 作業ファイルと最終成果物の区別

- `_reader/` 直下のファイルのみが最終成果物。点数・判定の根拠はここを参照する。
- `_reader/_work/<YYYYMMDD>/` のファイルは過程の記録。複数回の評価で上書きしない（日付フォルダで分離）。
- 「保存した」と報告してよいのは `_reader/` 直下の最終成果物が存在し `Read` で確認した後。

## `_meta.md` 更新（Editor Score / Consistency Audit 後）

Editor Score と Consistency Audit の実施後は、作品 `_meta.md` の「評価・足切り履歴」節を更新する。

- **評価履歴表**に行を追記する（既存行は削除しない）。
- 例: `| 20260608_1400 | Editor Score | 82 / 100 | — | _reader/score_20260608_1400.md |`
- 例: `| 20261004_1030 | Consistency Audit (design) | — | 矛盾0 / 要確認2 / 軽微1 | _reader/consistency_design_20261004_1030.md |`
- 例: `| 20261004_1100 | Consistency Audit (text) | — | 矛盾1 / 要確認0 / 軽微3 | _reader/consistency_text_20261004_1100.md |`
- Gate B で再監査した design は判定欄を「矛盾2→0」のように書く。
- 「足切りステータス」は足切り専用とし、Audit の結果を混ぜない。
- `_meta.md` に「評価・足切り履歴」節がまだない場合は、`_how_to/meta.md`（無ければ `_how_to.example/meta.md`）の「評価・足切り履歴」節を参照してテンプレートを挿入する。挿入位置は内部メタの直後・外部メタの直前。
- Consistency Audit の完了は、監査ファイルを保存して Read で確認し、`novel_consistency_audit_lint.py` が終了コード 0 を返し、評価履歴表へ追記したあとに報告する。

## 清書前後のスコア対応（版管理）

`rewrite.md` による清書（スキル **`novel-refinement-output`**）の前後で Editor Score が変化する場合の対応表テンプレ:

| 時点 | 本文バージョン | 評価ファイル |
|------|---------------|-------------|
| 清書前 | `_novel_text/novel_textXX.md`（現行） | `_reader/score_YYYYMMDD_HHMM.md`（清書前版） |
| 清書後 | `_novel_text_backup/novel_textXX_vNNN.md` 退避 → `_novel_text/` 更新 | `_reader/score_YYYYMMDD_HHMM.md`（再評価・新日時） |

運用ルール:
- 旧版の `score_*.md` は削除しない（改訂前スコアとして参照可能にする）。
- 作品 `_meta.md` の「評価履歴表」に清書前後を別行として記録する（どちらが清書前・後かを「備考」列に記載）。
- 両スコアの差分比較は `tools/novel_evaluation_diff.py` で行う（清書前後の `score_*.md` を時系列表示し、ポイント差分を `[+N]` / `[-N]` で示す）。

## 査証ログとの関係

- `_reader/` は評価本文の正本。
- `_workingspace/log/` は「評価を実施し、どのファイルへ保存したか」という作業事実だけを追記する。

## 関連

- 横断正本: `.rulesync/rules/workflow-specification.md`（評価ファイル命名と役割・住み分け・長文閾値）
- 足切りスキル: `.rulesync/skills/novel-reader-output/SKILL.md`
- 読み進み感想: `.rulesync/skills/novel-reader-walk/SKILL.md`
- 詳細仕様: `.rulesync/rules/workflow-specification.md`（Editor Score / Consistency Audit）
- 企画の設定監査（B4.5）: `.rulesync/skills/novel-planning/SKILL.md`
- 設定鮮度チェック: `tools/novel_audit_freshness.py`
- 監査ファイルの体裁検査: `tools/novel_consistency_audit_lint.py`
- 固有名詞の機械照合（任意）: `tools/novel_proper_noun_lint.py`
- 操作説明: `docs/workflow/reader-output.md`、`docs/workflow/instruction-driven.md`
