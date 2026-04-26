---
name: novel-tag-md-format
description: >-
  novels/<作品>/tag/<romaji>.md の見出し・Danbooru Tags 行・インデントを
  tools/forge_novel_tag_batch.py と整合させる互換フォーマット。Tag Mode 執筆時に従う。
targets: ["*"]
---

## 目的

`_how_to/tag.md` の内容（プロンプト・タグの作り方）に加え、**ファイルの Markdown 構造を一定に保ち**、次を曖昧にしない。

新規設計では、キャラクタータグの構造正本はスキル **`manga-prompt-ir`** の `schemas/character.py` と `examples/character.yaml` に寄せる。  
このスキルは、既存の `tools/forge_novel_tag_batch.py` と `tag/<romaji>.md` を使うための **Markdown 互換層**として残す。

- **`tools/forge_novel_tag_batch.py`** が `tag/*.md` から **Danbooru 行を抜き漏れなく抽出**できること。
- 人間の編集・差分でも **セクション境界がブレない**こと。

## 必須ルール（短く）

| 項目 | 規約 |
|------|------|
| ファイル名 | `tag/<romaji>.md`（画像は `tag/<romaji>/` に集約） |
| 状況ごとの見出し | **`## N. 見出し`** を推奨（`N` は 1 から連番）。`### N.` や行頭 `N.` も互換だが新規は `##` |
| Danbooru ラベル | 行を **`**Danbooru Tags:**`** のようにし、**コロンは `Tags` の直後**（太字の閉じ方は `_how_to/tag.md` の例に合わせる） |
| タグ本文 | **ラベルの次行・1行・カンマ区切り**。行頭インデントなし。複数行タグは不可（一括は1行目のみ） |
| Caption / 和訳 | `**Caption:**` / `**和訳:**` で揃える |

## 人間向けの全文

構造化入力の正本は **`manga-prompt-ir`**。既存 Markdown 形式の詳細は、**`_how_to/tag.md`** のセクション **「Markdown ファイル形式（`tag/<romaji>.md`・機械抽出と整合）」** を参照する。

矛盾した場合の判断:

1. キャラクター固定特徴・禁止変更項目・negative tags は `manga-prompt-ir` の YAML/Pydantic を優先する。
2. 既存バッチ抽出の互換性は、この Markdown 規約を優先する。

## 検証

```bash
python tools/forge_novel_tag_batch.py novels/<作品フォルダ> --dry-run
```

ジョブ数 0 や `Danbooru Tags を1件も抽出できませんでした` のときは、見出し形式・`Danbooru Tags:` の行・改行位置を見直す。

## 関連

- **固定外見（目・髪など）の一貫性**: スキル **`novel-tag-character-consistency`**（`character.md` と各状況ブロックの照合）
- 画像生成本体: スキル **`forge-txt2img`**（`tools/forge_generate.py`）
- フォルダ作成: スキル **`novel-image-layout`**（`tools/novel_image_layout.py`）
