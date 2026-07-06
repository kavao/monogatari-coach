# ユーザスキル雛形（`_how_to.example/skills/`）

このディレクトリは **雛形（テンプレート）** 置き場です。初回セットアップで **`_how_to/skills/<名前>/` にコピー**し、以降はコピー先を編集します。
**`.rulesync/skills/` の正本ではありません。** 公式のモード定義・エージェント必須ルールは **`.rulesync/rules/overview.md`** と **`.rulesync/skills/`** を参照してください。

- **作業中の一覧（コピー先）**: [`_how_to/skills/_index.md`](../../_how_to/skills/_index.md) — 雛形にない条項（例: ユーザだけが持つスキル）が表に出る場合があります。
## 一覧

| ID | パス | 概要 | 発動条件（実運用） |
|----|------|------|-------------------|
| kakuyomu-convert | [`kakuyomu-convert/SKILL.md`](kakuyomu-convert/SKILL.md) | `kakuyomu.csv` に基づきカクヨムルビ記法を `_novel_text`（または指定入力）から機械挿入し **`_novel_text_re` に出力**。実装は **`_how_to/tools/kakuyomu_ruby_apply.py`** | カクヨム投稿向けにルビ付き本文を出力するとき |
| episode-general-pick | [`episode-general-pick/SKILL.md`](episode-general-pick/SKILL.md) | general / common のフック・進行を **`novel_pick_registry.py`** の public list_id から抽選する雛形 | Plan Mode で一般向けエピソードたたき台を組み立てるとき |
| episode-mature-pick | — | **`_how_to/skills/episode-mature-pick/`**（user 領域のみ）。mature 向けフック・進行の完全版手順 | Plan Mode で mature 向けエピソードを組み立てるとき（user 領域に配置済みの場合） |

実運用で `character-body-pick` など雛形にないスキルがある場合、**[`_how_to/skills/_index.md`](../../_how_to/skills/_index.md)** の発動条件列を確認する（本表は雛形のみ）。

## 呼び出し

- **条件付き（推奨）**: 公式スキル（**novel-planning** 等）に発動条件がある場合、または **`_how_to/skills/_index.md`** の発動条件列に当てはまるとき、コピー先の `SKILL.md` を読む。
- **明示**: チャットや Cursor コマンドから **「`_how_to/skills/<skill>/SKILL.md` を読んで実行」** と指定してもよい。
