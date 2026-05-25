---
name: novel-refinement-output
description: >-
  rewrite.md による清書（文章校正）は、_novel_text_backup/ に旧版を退避してから
  novels/.../_novel_text/ を同一ファイル名で更新する。バックアップの版番号規則と反映手順を固定する。
  「退避してから加筆します」と述べたら宣言のみで終えず、同一ターンでツール実行まで進める（実行継続）。
---

## 目的

清書・文章校正フェーズで **どのディレクトリに何を書くか** を曖昧にしない。

- **初稿・執筆の正本**は **`_novel_text/novel_text*.md`**（スキル **`novel-text-file-output`**）。
- **`_how_to/rewrite.md` を適用した清書結果**は、**`_novel_text_backup/` に旧版を退避したうえで** **`_novel_text/`** を更新する（本スキル）。

## パス規則（必須）

| 役割 | ディレクトリ | ファイル名 |
|------|----------------|------------|
| 入力（リライト元） | `novels/<作品>/_novel_text/` | `novel_textXX.md`（項は `novel_textXX_Y.md` と同じ規則） |
| 出力（rewrite 後） | `novels/<作品>/_novel_text/` | **入力と同一のファイル名** |
| 旧版バックアップ | `novels/<作品>/_novel_text_backup/` | **`<元ファイル名>_vNNN.md`**（例: `novel_text01_v001.md`） |

- **`_novel_text_backup/` が無ければ作成する**。
- **バックアップの版番号は 3 桁ゼロ埋めの連番**を用いる。既存の最大番号に `+1` した値を次版とし、同一元ファイルごとに採番する。
- **会話欄への本文貼り付けだけで完了としない**。必ず **`_novel_text/novel_textXX.md`** を更新する。

## 計画表明だけで終わらない（実行継続）

「旧版を退避してから加筆します」「退避→加筆→確認をツールで行います」などと述べたら、**宣言だけで応答を終えない**。

1. **同一ターン優先**: 可能な限り、**`_novel_text_backup/` へ旧版退避 → `_novel_text/` を更新 → `Read` または `novel_char_count.py`** まで **同一応答内**で完了させる。
2. **応答が分割される場合**: 続きのターンでは **説明のやり直しをせず**、未完了の最初のステップから **すぐツールを実行**する（前置きの繰り返し禁止）。
3. **最小進捗**: 一度に全部できない場合でも、**バックアップファイルの作成または正本ファイルの更新のどちらか**は同一ターンで実行する。

**画像生成バッチ**（`image_provider_generate.py`、`image_provider_novel_*_batch.py`）は **上記「同一ターン優先」の対象外**。スキル **`image-provider（旧 forge-txt2img）`** に従い、**`--dry-run` → ユーザー承認 → 本番 → 保存先でのファイル確認**とする。

一般の「これからファイルを更新します」系の予告も、スキル **`novel-text-file-output`** の「ツール予告と応答の継続」に従う（画像生成は除く）。

## 他フェーズとの関係（参照）

- **執筆直後の機械校正（`grammar --fix`）**: スキル **`novel-text-rewrite-lint`**。`_novel_text` 保存後に誤打（`　「`・半角 `,`・`…` 等）を **安全な置換だけ** 直す。**本スキル（rewrite 清書）の前**に行ってよいが、**代わりにはしない**。
- **Writing Mode §2.3 手順7（reader.md による清書）**: 手順どおりなら **`_novel_text/` 内の同一ファイル名を置換**する（下読み・体裁の清書）。
- **本スキル（rewrite.md による文章校正）**: 手順7と同様に **`_novel_text/`** を更新するが、**更新前に必ず `_novel_text_backup/` へ旧版を退避する**。

## 手順（推奨順）

1. **作業計画**: 対象の `novel_textXX.md` と、強化したい点（分量・描写・文体）を明示する。
2. **入力を読む**: `_novel_text/novel_textXX.md` を正とする。
3. **バックアップ採番**: `_novel_text_backup/` に、上書き対象の `novel_textXX.md` を **`<元ファイル名>_vNNN.md`** の形式で退避する。
4. **rewrite 適用**: `_how_to/rewrite.md` に従いリライトする（目安・句読点ルールは同ファイル。**§9 章番号・前章メタ参照の除去**を含む）。
5. **出力**: `_novel_text/novel_textXX.md` を**直接更新**する。
6. **確認**: **`Read`** で末尾などを確認するか、**`python tools/novel_char_count.py`** で更新後の **`_novel_text/`** を確認する（定義はスキル **`novel-char-count`**）。
7. **ストーリー反映**: スキル **`novel-story-reflection`** に従い、`_meta.md` の進捗・文字数・次回タスクを更新する。
8. **清書後 lint**: `python tools/novel_text_rewrite_lint.py novels/NNN --profile full` のあと、**`--strict`**（既定 `default`）で exit 0 を確認してから「清書完了」と報告する（スキル **`novel-text-rewrite-lint`**）。
   - **部分加筆・シーンの途中挿入**でも手順 3〜7 は同じ。**確認は末尾だけにせず**、**追加した段落の前後を含む範囲を `Read`** し、正本に意図どおり残っていることを検証する。

## 査証・メタ

- `_meta.md` や `_workingspace/log/` に文字数を書くときは **`novel_char_count.py` の集計値**を根拠にする。

## 関連

- プロジェクト全体: **`.rulesync/rules/overview.md`** の「2.3 Writing Mode」「2.5 Writing Mode Refinement」
- 初稿のファイル出力: **`novel-text-file-output`**
- 技法: **`_how_to/rewrite.md`**
- 執筆直後の機械校正・清書後 lint: **`novel-text-rewrite-lint`**
