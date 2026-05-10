# カクヨム変換 — ユーザ向けヒント（最短チェックリスト）

運用で押さえることは、次の **2点だけ** です。

## 1. コピー（どこに何を置くか）

- **本文の正本**は `novels/<作品>/_novel_text/`（書き換えない運用ならそのまま）。
- **ルビ付きの出力**は必ず **`novels/<作品>/_novel_text_re/`**。スクリプト既定がこれです。
- **ミラー（手で `_novel_text` を `_novel_text_re` に複製）**は必須ではありません。`kakuyomu_ruby_apply.py` が入力 `_novel_text` から直接 `_novel_text_re` に書けます。
- 作品フォルダに **`kakuyomu.csv`** を置く（列は `match`, `reading`, 省略可で `mode`）。書き方のサンプルは同梱の **`kakuyomu.csv.example`**。

## 2. カクヨムプラグイン（チェック用）

- カクヨムの記法・ルビの長さなどは **[カクヨムヘルプ「記法一覧」](https://kakuyomu.jp/help/entry/notation)** を正とする。
- ルビの機械挿入は **`_how_to/tools/kakuyomu_ruby_apply.py`**（詳細は `SKILL.md`）。
- プラグインや投稿画面での見え方を確認するときは、**`_novel_text_re` の Markdown** をソースにする（`_novel_text` を直接ルビ加工しない運用を推奨）。

---

## 初回セットアップ（この雛形の使い方）

1. 本ディレクトリ全体を **`_how_to/skills/kakuyomu-convert/`** にコピーする（既に存在する場合は `SKILL.md` と `kakuyomu.csv.example` だけ上書きでよい）。
2. 各作品で `kakuyomu.csv.example` を **`novels/<作品>/kakuyomu.csv`** として複製し、行を追加・編集する。
