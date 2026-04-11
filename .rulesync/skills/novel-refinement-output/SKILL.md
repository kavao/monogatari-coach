---
name: novel-refinement-output
description: >-
  rewrite.md による清書（文章校正）の成果物を novels/.../_novel_text_re_/ に、
  _novel_text/ と同一のファイル名で保存する。バックアップ・正本への反映タイミングを固定する。
---
## 目的

清書・文章校正フェーズで **どのディレクトリに何を書くか** を曖昧にしない。

- **初稿・執筆の正本**は **`_novel_text/novel_text*.md`**（スキル **`novel-text-file-output`**）。
- **`_how_to/rewrite.md` を適用したリライト結果**は、初稿と**混線しない**よう **`_novel_text_re_/`** に出力する（本スキル）。

## パス規則（必須）

| 役割 | ディレクトリ | ファイル名 |
|------|----------------|------------|
| 入力（リライト元） | `novels/<作品>/_novel_text/` | `novel_textXX.md`（項は `novel_textXX_Y.md` と同じ規則） |
| 出力（rewrite 後） | `novels/<作品>/_novel_text_re_/` | **入力と同一のファイル名** |

- **`_novel_text_re_/` が無ければ作成する**（空の `.gitkeep` を置いてもよい）。
- **会話欄への本文貼り付けだけで完了としない**。必ず **`_novel_text_re_/novel_textXX.md`** を更新する。

## 他フェーズとの関係（参照）

- **Writing Mode §2.3 手順7（reader.md による清書）**: 手順どおりなら **`_novel_text/` 内の同一ファイル名を置換**する（下読み・体裁の清書）。
- **本スキル（rewrite.md による文章校正）**: 成果物は **`_novel_text_re_/`** に書く。手順7と**別フォルダ**になる。

## 手順（推奨順）

1. **作業計画**: 対象の `novel_textXX.md` と、強化したい点（分量・描写・文体）を明示する。
2. **入力を読む**: `_novel_text/novel_textXX.md` を正とする。
3. **rewrite 適用**: `_how_to/rewrite.md` に従いリライトする（目安・句読点ルールは同ファイル）。
4. **出力**: `_novel_text_re_/novel_textXX.md` に**書き込み**（新規・置換）。
5. **確認**: **`Read`** で末尾などを確認するか、**`python tools/novel_char_count.py`** で清書前（`_novel_text/`）後（`_novel_text_re_/`）を比較する（定義はスキル **`novel-char-count`**）。
6. **`_novel_text` へ清書を「正本として」反映する場合（任意・ユーザー合意後）**  
   - 先に **`_novel_text_backup/`** に、上書き対象の `novel_textXX.md` を退避する。  
   - その後、`_novel_text_re_/novel_textXX.md` の内容で `_novel_text/novel_textXX.md` を置換する。  
   - **反映の有無はプロジェクトの運用で決める**（推敲完了まで `_novel_text_re_` のみを正とする、など）。

## 査証・メタ

- `_meta.md` や `_workingspace/log/` に文字数を書くときは **`novel_char_count.py` の集計値**を根拠にする。

## 関連

- プロジェクト全体: **`.rulesync/rules/overview.md`** の「2.3 Writing Mode」「2.5 Writing Mode Refinement」
- 初稿のファイル出力: **`novel-text-file-output`**
- 技法: **`_how_to/rewrite.md`**
