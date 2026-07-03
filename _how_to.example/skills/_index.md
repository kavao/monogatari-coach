# ユーザスキル雛形（`_how_to.example/skills/`）

このディレクトリは **雛形（テンプレート）** 置き場です。初回セットアップで **`_how_to/skills/<名前>/` にコピー**し、以降はコピー先を編集します。
**`.rulesync/skills/` の正本ではありません。** 公式のモード定義・エージェント必須ルールは **`.rulesync/rules/overview.md`** と **`.rulesync/skills/`** を参照してください。

- **作業中の一覧（コピー先）**: [`_how_to/skills/_index.md`](../../_how_to/skills/_index.md) — 雛形にない条項（例: ユーザだけが持つスキル）が表に出る場合があります。
## 一覧

| ID | パス | 概要 |
|----|------|------|
| kakuyomu-convert | [`kakuyomu-convert/SKILL.md`](kakuyomu-convert/SKILL.md) | `kakuyomu.csv` に基づきカクヨムルビ記法を `_novel_text`（または指定入力）から機械挿入し **`_novel_text_re` に出力**。実装は **`_how_to/tools/kakuyomu_ruby_apply.py`** |

## 呼び出し（手書き版）

チャットや Cursor コマンドから **「`_how_to/skills/<skill>/SKILL.md` を読んで実行」** と明示するとよいです。
**`.rulesync/rules/overview.md` には載せない**運用でも、本インデックスからたどれます。
