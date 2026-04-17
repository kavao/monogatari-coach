---
name: novel-refinement-output
description: >-
  rewrite.md による清書（文章校正）は、_novel_text_backup/ に旧版を退避してから
  novels/.../_novel_text/ を同一ファイル名で更新する。バックアップの版番号規則と反映手順を固定する。
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

## 他フェーズとの関係（参照）

- **Writing Mode §2.3 手順7（reader.md による清書）**: 手順どおりなら **`_novel_text/` 内の同一ファイル名を置換**する（下読み・体裁の清書）。
- **本スキル（rewrite.md による文章校正）**: 手順7と同様に **`_novel_text/`** を更新するが、**更新前に必ず `_novel_text_backup/` へ旧版を退避する**。

## 手順（推奨順）

1. **作業計画**: 対象の `novel_textXX.md` と、強化したい点（分量・描写・文体）を明示する。
2. **入力を読む**: `_novel_text/novel_textXX.md` を正とする。
3. **バックアップ採番**: `_novel_text_backup/` に、上書き対象の `novel_textXX.md` を **`<元ファイル名>_vNNN.md`** の形式で退避する。
4. **rewrite 適用**: `_how_to/rewrite.md` に従いリライトする（目安・句読点ルールは同ファイル）。
5. **出力**: `_novel_text/novel_textXX.md` を**直接更新**する。
6. **確認**: **`Read`** で末尾などを確認するか、**`python tools/novel_char_count.py`** で更新後の **`_novel_text/`** を確認する（定義はスキル **`novel-char-count`**）。

## 査証・メタ

- `_meta.md` や `_workingspace/log/` に文字数を書くときは **`novel_char_count.py` の集計値**を根拠にする。

## 関連

- プロジェクト全体: **`.rulesync/rules/overview.md`** の「2.3 Writing Mode」「2.5 Writing Mode Refinement」
- 初稿のファイル出力: **`novel-text-file-output`**
- 技法: **`_how_to/rewrite.md`**
