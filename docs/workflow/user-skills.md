# ユーザスキル（プラグイン相当）

このガイドを読むと、**公式スキル（`.rulesync/skills/`）とは別に**、自分用の手順・ツール連携を **`_how_to/skills/`** に置くときの置き場所と、雛形との関係が分かります。

Monogatari Coach は、投稿サイト向けの変換や個人用ワークフローを **リポジトリに載せずに済む場合でも**、共有したいときは **雛形を `_how_to.example/` に置き、作業は `_how_to/` で行う** パターンで整理できます。

---

## TL;DR

- **「ユーザプラグイン」に相当するもの**は、このリポジトリでは **`_how_to/skills/<名前>/`** に `SKILL.md` を置く運用を指します（`.rulesync/skills/` の公式スキルではありません）。
- **スクリプト本体**は `.rulesync/skills/` に置けないため、Python は原則 **`_how_to/tools/`** に置き、`SKILL.md` からパスで参照します（リポジトリ全体の正式ツールへ昇格するときは **`tools/`** を検討）。
- **雛形の正本**は **`_how_to.example/skills/<名前>/`**、一覧は **`_how_to.example/skills/_index.md`** と **`_how_to/_index.md`** の項0・項14などから辿れます。
- 横断の定義（`_how_to/` と `docs/`、正本と副本）は **[`.rulesync/rules/concepts.md`](../../.rulesync/rules/concepts.md)** を参照してください。

---

## 公式スキルとの違い

| 項目 | 公式スキル | ユーザスキル |
|------|------------|----------------|
| 置き場 | `.rulesync/skills/<名前>/`（`SKILL.md` のみ） | `_how_to/skills/<名前>/` |
| 対象 | LLM の既定動作・ルールと連動した仕様 | 個人・チームの試行・外部サイト連携など |
| Python | `tools/` に実装（スキル直下には置かない） | `_how_to/tools/`（または昇格時に `tools/`） |

---

## 雛形と作業コピー

1. **`_how_to.example/skills/<名前>/`** に、共有したい **最短の `SKILL.md`** と、必要なら **ヒント・サンプル設定**（例: CSV の `.example`）を置く。
2. 手元では **`_how_to/skills/<名前>/`** にコピーして編集する（`_how_to/` はユーザー領域として差分が残ってよい）。
3. 一覧は **`_how_to.example/skills/_index.md`**（雛形）と **`_how_to/skills/_index.md`**（実運用）の両方を更新すると迷子が減ります。長文は `_index.md` に書かず **`SKILL.md` に集約**します。

---

## 例：カクヨム向けルビ（kakuyomu-convert）

カクヨムのルビ記法を本文へ機械挿入する流れの一例です。

- **雛形**: [`_how_to.example/skills/kakuyomu-convert/`](../../_how_to.example/skills/kakuyomu-convert/)（`USER_HINTS.md`、`kakuyomu.csv.example` など）
- **実装**: [`_how_to/tools/kakuyomu_ruby_apply.py`](../../_how_to/tools/kakuyomu_ruby_apply.py)
- **作品側**: `novels/<作品>/kakuyomu.csv` と、出力先として `_novel_text_re` を使う運用（詳細は各 `SKILL.md`）

---

## 関連リンク

- [Workflow の入口](index.md)
- [`_how_to/tools/README.md`](../../_how_to/tools/README.md)（ユーザ用 Python の置き場）
- [Project Structure の `_how_to/` ガイド](../project-structure/how-to-area.md)
