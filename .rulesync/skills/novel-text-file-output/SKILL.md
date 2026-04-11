---
name: novel-text-file-output
description: >-
  小説本文を会話にだけ書かず、novels/.../_novel_text/novel_text*.md へ必ず保存する。
  執筆直後にファイル更新を Read または novel_char_count.py で確認する。
targets: ["*"]
---

## 目的

**本文の正本はリポジトリ上の Markdown ファイル**とする。モデルやクライアントによっては、**会話画面にだけ** 章本文を出し、**`_novel_text` を更新しない**ことがある（**Auto 以外・別 LLM 選択時**で起きやすい）。本スキルはその抜けを防ぐ。

## 必須（執筆ターンごと）

1. **書き込み**: `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）に対し、**新規作成・追記・置換**のいずれかで **必ずファイルを更新**する。長文をチャットに貼るだけで終えない。
2. **報告**: ユーザー向け返答に、**更新したファイルのパス**（リポジトリ相対でよい）を明示する。
3. **確認**（いずれかを実行する）:
   - **`Read`** ツールで、更新した `novel_text*.md` を **少なくとも末尾数十行** 読み、意図した内容が保存されていることを確認する。
   - または **`python tools/novel_char_count.py <対象ファイルまたは作品フォルダ>`** を実行し、**分量がゼロでないこと・章の想定と整合すること**を確認する（定義はスキル **`novel-char-count`**）。

## 査証・メタ

- 進捗や文字数を **`_workingspace/log/`** や **`_meta.md`** に書くときは、**ファイルに存在する内容**に基づく（会話の記憶だけに頼らない）。

## 関連

- 執筆**前**の資料・フォルダ: スキル **`novel-project-readiness`**（`tools/novel_project_check.py`）
- **`rewrite.md` による清書の出力先**（`_novel_text_re_/`）: スキル **`novel-refinement-output`**
- 分量の公式カウント: **`novel-char-count`**（`tools/novel_char_count.py`）
- プロジェクト全体のルール: **`.rulesync/rules/overview.md`** の「2.3 Writing Mode」「2.3.1 本文出力の確認」
