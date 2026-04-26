---
name: manga-prompt-ir
description: >-
  漫画ページ・漫画コマ・キャラクター定義を YAML/JSON/Pydantic の中間表現で管理し、
  画像生成向けの自然文プロンプト、タグ列、テキスト要素へ変換する。
targets: ["*"]
---

# Manga Prompt IR

## 目的

キャラクタータグと漫画タグの正本を、従来の Markdown 抽出だけに依存せず、**Pydantic モデルを正**、**YAML を人間編集用**、**JSON を内部処理・機械連携用**として扱う。

このスキルは、次の3つを分離して管理する。

- **キャラクター定義**: 外見・衣装・性格・固定タグ・禁止変更項目
- **漫画ページ定義**: ページ単位のレイアウト、コマ、人物、セリフ、効果音
- **レンダリング**: 画像生成モデルごとの自然文プロンプト、タグ列、テキスト要素抽出

## 正本の優先順位

1. `schemas/*.py`: Pydantic v2 モデル。構造・必須項目・型の正本。
2. `examples/*.yaml`: 人間が編集する入力例。作品ごとの YAML はこの形に寄せる。
3. `converters/*.py`: YAML/JSON を読み、モデル検証後にプロンプトへ変換する参考実装。
4. 従来の `tag/<romaji>.md` / `manga/manga_XX.md`: 既存ツール互換の出力・移行元として扱う。

## 運用方針

- このIRは、生成途中で壊れたら作り直せる **再生成可能な中間データ**として扱う。正本性の中心は、YAML形式そのものではなく、そこに入っている **日本語の意味・人物関係・場面意図・セリフ帰属**に置く。
- 小説本文からの変換を主体にする場合、最初のIRは荒くてもよい。品質ゲートで意味を補い、必要ならIR全体を再出力する。
- 新規のキャラクタータグは、まず `character.yaml` 相当の構造へ落とす。
- 新規の漫画タグは、まず `manga_page.yaml` 相当の構造へ落とす。
- `character_id` はキャラクター一貫性の主キーとし、ページ側の `character_ids` と各コマの `subjects[].character_id` から参照する。
- セリフ、モノローグ、ナレーション、効果音は混ぜず、`text.dialogue` / `text.monologue` / `text.narration` / `text.sfx` に分ける。
- 画像生成モデルが文字描画を苦手とする場合に備え、テキスト要素は `extract_text_elements()` で別処理できる形にする。
- `negative_tags` はキャラクター側とページ側の両方に持たせ、最終レンダリング時に結合する。
- 漫画固有タグ（画風・レイアウト・トーン）とキャラクター固有タグ（髪・目・衣装・種族・固定小物）は分けて保持する。

## 移行ルール

既存の Markdown 資産は、すぐに破棄しない。

- `tag/<romaji>.md` は `character.yaml` へ写経・正規化し、当面は `Danbooru Tags` の互換出力先として残す。
- `manga/manga_XX.md` は `manga_page.yaml` へ写経・正規化し、当面は Step1 / Step2 の互換出力先として残す。
- 画像生成バッチが Markdown しか読めない間は、YAML を正として Markdown 互換ブロックを生成する。
- 既存ツールを正式に更新するときは、`tools_temp/` で抽出・変換を試作してから `tools/` へ整理して反映する。

## 必須チェック

生成または改稿した YAML は、次を満たすこと。

- YAML が Pydantic モデルで検証できる。
- 自然文プロンプトを生成できる。
- タグ列を生成できる。
- テキスト要素だけを抽出できる。
- キャラクター固定特徴が、登場するすべてのコマへ引き継がれる。
- ページ単位で、コマ数、読み順、段・大小・視線誘導のいずれかが読める。

## 参考コマンド

依存パッケージはリポジトリルートで導入する。

```bash
python -m pip install -r requirements.txt
```

スキル内サンプルの検証:

```bash
python -m pytest .rulesync/skills/manga-prompt-ir/tests
```

作品フォルダ内のIR検証:

```bash
python tools/novel_prompt_ir_validate.py novels/<作品フォルダ>
```

YAML/JSON IR から既存バッチ互換 Markdown を出力:

```bash
python tools/novel_prompt_ir_export_md.py \
  --character novels/<作品>/tag/characters/<character_id>.yaml \
  --manga-page novels/<作品>/manga/pages/manga_01_p01.yaml \
  --output-dir tools_temp/ir_export_sample \
  --manga-stem manga_01
```

依存関係:

- Pydantic v2
- PyYAML
- pytest

## 関連スキル

- `novel-tag-md-format`: 既存 Markdown 互換のキャラクタータグ形式
- `novel-tag-character-consistency`: キャラクター固定特徴の照合
- `manga-tag-character-sync`: 漫画コマへのキャラクター特徴継承
- `manga-tag-quality-gate`: 主語・行為・レイアウトの品質確認
- `forge-txt2img`: 生成プロバイダへの最終受け渡し
