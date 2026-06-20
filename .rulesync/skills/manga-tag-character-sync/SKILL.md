---
name: manga-tag-character-sync
description: >-
  Manga Tag Mode で manga/pages/*.yaml の漫画ページIRを作成・改稿するときに、
  character.md と tag/characters/*.yaml を正として固定外見・服装・小物・種族特徴を継承し、
  コマごとの subjects / prompt_tags へ矛盾なく反映する。
  manga/manga_XX.md は必要時に YAML からエクスポートする人間向けの副本（バッチ互換）として扱う。
targets: ["*"]
---

## 目的

漫画タグはコマごとに状況やアングルが変わる一方で、**同一人物の識別に必要な固定特徴**はぶらしてはいけない。

本スキルは、`manga/pages/*.yaml` の漫画ページIRを作るときに、**`character.md` と `tag/characters/*.yaml` を先に読み、固定特徴を毎コマへ反映する手順**を固定する。

`manga/manga_XX.md` は `tools/image_provider_novel_manga_batch.py` 向けの**互換出力（人間向けの可読副本）**であり、Manga Tag Mode の初手で直接新規作成して**唯一の正本**にしない。既存 Markdown は移行・比較・推敲・生成直前の確認に使う。

## 正本・参照

| 正本 | 用途 |
|------|------|
| `novels/<作品>/tag/characters/<character_id>.yaml` | YAML/JSON 化後のキャラクター定義正本。`character_id` を主キーにして漫画ページから参照する。 |
| `novels/<作品>/character.md` | 外見・体格・服装・種族・持ち物のプロフィール正本。ここに無い特徴を漫画タグだけで増やさない。 |
| `novels/<作品>/_novel_text/novel_textXX*.md` | そのページの場面・人物・会話・小道具の本文根拠。漫画ページIR作成時に参照する。 |
| `novels/<作品>/manga/pages/manga_XX_pYY.yaml` | 漫画ページ定義正本。コマ・人物・セリフ・効果音・タグを分離する。 |
| `novels/<作品>/tag/<romaji>.md` | Danbooru Tags の互換運用形（人間向けの可読副本）。英語タグへの落とし方の参考・手作業確認に使う。 |
| `novels/<作品>/manga/manga_XX.md` | 既存バッチ互換・可読副本。移行元・推敲・生成直前の確認先。ページ定義の正本は `manga/pages/*.yaml`。 |
| `_how_to/manga.md` | コマ構成・出力形式・抽象度の基準。 |
| `_how_to/manga_tag.md` | 漫画向けタグ表現の参考。 |

## 反映の優先順位

1. **固定特徴**は、構造化定義がある場合は `tag/characters/<character_id>.yaml` を最上位の正とする。
2. 構造化定義がない作品では `character.md` を正とする。
3. **英語タグへの落とし方**は `000_base.danbooru_tags` / `manga_rules.consistency_tags` と、既存 `tag/<romaji>.md` を参考にする。
4. コマごとの状況・構図・アクションは、本文と `manga/pages/*.yaml` の内容に従う。
5. 既存 `manga/manga_XX.md` は、YAML が無い場合の移行元または互換出力の確認先に限って参照する。
6. 競合したときは **状況より固定特徴を優先**し、必要なら状況タグ側を調整する。

## 手順

### 1. 対象キャラを確定する

- 対象本文（`_novel_text/novel_textXX*.md`）と `manga/pages/*.yaml` から、ページに出る人物を洗い出す。
- YAML 化済みの場合は、`character_ids` と `panels[].subjects[].character_id` を先に確認する。
- 各人物について、対応する `tag/characters/<character_id>.yaml` と、必要に応じて `tag/<romaji>.md` があるか確認する。
- 既存 `manga/manga_XX.md` は、旧来の Markdown 資産から IR へ移行するときや、人物・タグの人間向け確認の補助として読む。

### 2. 固定特徴を抜き出す

各キャラについて、最低でも次をメモする。

- 髪: 色、長さ、前髪、結び方
- 目: 色、印象
- 肌: 明るさ、種族由来の特徴
- 体格: 細身、筋肉質、小柄など
- 服装: 通常衣装、制服、鎧、職業装備など
- 種族・耳・角・羽・尻尾など
- 固定小物: 眼鏡、リボン、武器、アクセサリ

### 3. 継承タグを作る

- `tag/characters/<character_id>.yaml` の `000_base.danbooru_tags` / `manga_rules.consistency_tags` から、**状況が変わっても残すべきタグ**を拾う。
- 服装・状態差分がある場合は、`manga/pages/*.yaml` の `panels[].subjects[]` に `variant_id` / `prompt_variant_id` / `costume_variant` のいずれかを入れ、`tag/characters/<character_id>.yaml` の `prompt_variants[].variant_id` と一致させる。
- ページYAMLを単体で読める原盤にする場合は、`tools/novel_prompt_ir_embed_snapshots.py novels/<作品>` を実行し、`character_snapshots` にそのページで使う固定特徴・衣装・バリアントタグを埋め込む。
- 互換タグが必要な場合は `tag/<romaji>.md` の Danbooru Tags 行も確認する。
- 服装がシーンで変わる場合でも、**顔・髪・目・肌・種族・固定小物**は原則維持する。
- 漫画タグでは、必要ならタグを少し短くしてよいが、**識別に必要なタグは落とさない**。

### 4. 各コマへ反映する

各コマのタグは次の順で組む。

1. 画風・漫画表現
2. 場所・時間・背景
3. 登場キャラごとの固定特徴
4. そのコマ固有の表情・ポーズ・アクション
5. 必要な効果や演出

固定特徴は、同じキャラが出るコマでは**毎回入れる前提**で扱う。

### 5. 禁止事項

- `character.md` に無い外見特徴を勝手に追加しない。
- `tag/<romaji>.md` と矛盾する髪色・目色・種族タグを混ぜない。
- コマごとに固定特徴を省略しすぎて別人化させない。
- 服装変更の根拠が無いのに衣装タグを切り替えない。

## 指示文の型

ユーザーから漫画タグ作成を受けたときは、次の意図で実行する。

```text
_novel_text と tag/characters/*.yaml / character.md を正として固定特徴を継承し、
manga/pages/*.yaml の subjects / prompt_tags へ矛盾なく反映する。
manga/manga_XX.md は必要時に YAML からエクスポートする（人間向けの副本・バッチ互換）。
```

## 関連

- ルール: `.rulesync/rules/overview.md` の Manga Tag Mode
- 画像タグ整合: スキル `novel-tag-character-consistency`
- 画像生成: スキル `image-provider（旧 forge-txt2img）`
