---
name: novel-evaluation-output
description: >-
  Editor Score・Consistency Audit・Synopsis の評価結果を novels/.../_reader/ に保存し、
  チャットには要約だけを返す。novel-reader-output（足切り）とは別スキルとして分離し、
  保存先ファイル名・前処理手順・完了条件を固定する。
targets: ["*"]
---

## 目的

First Reader（足切り）通過後の深掘り評価モード（Editor Score / Consistency Audit / Synopsis）で、評価結果の所在を曖昧にしない。

横断正本は **`.rulesync/rules/workflow-specification.md`** の「評価ファイル命名と役割」および「足切りと深掘り評価の住み分け」。このスキルは、それらの保存条件を満たすための実行手順を定める。

**重要**: 足切り（First Reader）は `.rulesync/skills/novel-reader-output/SKILL.md` が正とする。本スキルは足切り手順を上書きしない。

## 保存先（必須）

| 種別 | 参照する技法 | 保存先 |
|------|--------------|--------|
| Editor Score | `_how_to/editor_score.md` | `novels/<作品>/_reader/score_YYYYMMDD_HHMM.md` |
| Consistency Audit | `_how_to/consistency_audit.md` | `novels/<作品>/_reader/consistency_YYYYMMDD.md` |
| Synopsis（前処理） | `_how_to/novel_synopsis_for_review.md` | `novels/<作品>/_reader/synopsis_YYYYMMDD.md` |

- `_reader/` が無ければ作成する。
- チャット欄に本文を書いただけでは完了ではない。評価本文は必ず上記ファイルへ保存する。
- 保存したファイルパスをチャットで明示してから完了扱いにする。

## 評価前チェックリスト

各モード共通で、評価を開始する前に次の順序で確認する。

1. **足切り済みであること**を確認する（`_reader/YYYYMMDD_HHMM.md` の判定が「読むべき」）。
2. `config.md` を Read し、作品名・ジャンル・ターゲット層を確認する。
3. 対象 `_novel_text/*.md` を Read する。
4. `character.md` / `world.md` / `design_specification.md` を Read する（Editor Score / Consistency Audit）。
5. `python tools/novel_char_count.py novels/<作品>` を実行し、対象範囲の文字数を取得する。
6. **長文チェック**: 合計30,000字超 or 章単体8,000字超の場合 → Synopsis 先行を推奨（詳細は「長文対応」節）。

## Editor Score の手順

1. 評価前チェックリストを実施する。
2. `_how_to/editor_score.md` を Read する。
3. 5項目100点満点で採点し、致命的弱点・改善候補・設計との乖離を明示する。
4. 結果を `_reader/score_YYYYMMDD_HHMM.md` に保存する。
5. 作品 `_meta.md` の「評価・足切り履歴」節に Editor Score のパスと点数を追記する。

チャットへは「総合点・致命的弱点の件数・保存先パス」の3点のみ返す。

## Consistency Audit の手順

1. 評価前チェックリストを実施する（設計書読み込みが必須）。
2. `_how_to/consistency_audit.md` を Read する。
3. 全章を横断して矛盾・表記揺れ・未回収伏線を洗い出し、表形式で記録する。
4. 結果を `_reader/consistency_YYYYMMDD.md` に保存する。

チャットへは「矛盾件数（矛盾/要確認/軽微の内訳）・保存先パス」を返す。

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

## `_meta.md` 更新（Editor Score 後）

Editor Score 実施後は、作品 `_meta.md` の「評価・足切り履歴」節を更新する。

- **評価履歴表**に Editor Score 行を追記する（既存行は削除しない）。
- 例: `| 20260608_1400 | Editor Score | 82 / 100 | — | _reader/score_20260608_1400.md |`
- `_meta.md` に「評価・足切り履歴」節がまだない場合は、`_how_to/meta.md` の「§II. 評価・足切り履歴」を参照してテンプレートを挿入する。挿入位置は内部メタ（§I）の直後・外部メタの直前。

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
- 詳細仕様: `.rulesync/rules/workflow-specification.md`（Editor Score / Consistency Audit）
- 操作説明: `docs/workflow/reader-output.md`、`docs/workflow/instruction-driven.md`
