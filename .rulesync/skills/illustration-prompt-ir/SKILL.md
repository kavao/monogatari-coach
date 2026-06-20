---
name: illustration-prompt-ir
description: >-
  小説本文から挿絵・章扉・表紙向けの YAML IR を作成し、漫画ではない一枚絵として
  人物・場面・構図・光・タグ・生成指示を構造化する。
targets: ["*"]
---

# Illustration Prompt IR

> 横断正本: `.rulesync/rules/concepts.md` の「挿絵IR」を正とする。型・フィールドは `tools/manga_prompt_ir/schemas/manga_page.py` の `MangaPagePrompt` を使い、`meta.intent: illustration` で漫画ページと区別する。

## 目的

小説本文から「漫画ではない一枚絵」を作るための中間表現を、YAML IR として保持する。
章頭挿絵、本文中の山場、情景カット、表紙のような画像を、人物・場面・構図・光・タグ・ネガ・生成指示に分けて管理する。

## 前提：計画 MD の確認（必須）

Illustration Tag Mode（YAML IR 作成）は **Step 2** である。開始前に必ず以下を確認する:

1. `_meta.md` §3.2 章別割当表を読み、対象章の「枚数」が 1 または multiple であることを確認する。
2. `illustrations/plans/chapter_plan.md`（または `cover_plan.md`）に採用節が記入済みであることを確認する。
3. 計画 MD が未作成の場合は、先に **`illustration-plan` スキル（Step 1）** を実行する。
4. 章が 0枚と確定している場合は YAML を作成しない。

**禁止**: 計画 MD（Step 1）を経由せず YAML だけを新規作成して Illustration Tag Mode を完了扱いにしない。

## 正本

- **計画 MD（Step 1）**: `novels/<作品>/illustrations/plans/cover_plan.md`（表紙）/ `chapter_plan.md`（章）
- **YAML IR（Step 2）**: `novels/<作品>/illustrations/pages/illustration_XX_pYY.yaml`
- **画像保存先**: `novels/<作品>/illustrations/_assets/illustration_XX/`
- **キャラクター外見**: `novels/<作品>/tag/characters/<character_id>.yaml`
- **互換 Markdown**: `novels/<作品>/illustrations/illustration_XX.md`（任意。初期運用では必須にしない）

## 漫画IRとの差分

- `meta.intent` は `illustration`。
- `panels[]` は漫画のコマではなく、構図の構成セルとして扱う。
- 単体挿絵は `panels[]` 1件を推奨する。
- 群像や複合構図では、`panels[]` を複数セルにして、各セルの `summary` / `subjects` / `composition.*_en` に配置意図を書く。
- **複合構図が要る作品だけ**セル複数にする判断・書き方・生成方針（1枚合成／セル別）は **`.rulesync/rules/overview.md`** の Illustration Tag Modeを正とする。
- 既定は枠線なし・パネル境界なしの一枚絵。枠や分割画面を使うときは、`manga.panel_layout` または `render_instruction.user_directives.page_notes` に理由を書く。
- `text.dialogue` / `text.narration` / `text.monologue` / `text.sfx` は原則空。画像内文字が必要な場合のみ明示する。

## 作業手順

1. 作品フォルダの `_meta.md` を確認し、挿絵の密度・優先場面・表紙方針を見る。
2. 参照する本文 `_novel_text/novel_text*.md` と、登場人物の `tag/characters/*.yaml` を確認する。
3. `illustrations/pages/illustration_XX_pYY.yaml` を作成する。
4. `render_instruction` に、一枚絵としての作画依頼、構成セルの扱い、キャラクター継承、文字を入れない方針を書く。
5. `manga.panel_layout` には「枠線なし・一枚絵・セル境界なし」など、漫画の段組ではなく画面構成を書く。
6. `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` で検証する。
7. `python tools/image_provider_novel_illustration_batch.py novels/<作品> --dry-run` で生成ジョブを確認する。
8. 画像生成は `image-provider` スキルの dry-run → ユーザー承認 → 本番 → 保存先確認の順に進める。

## 生成既定値

挿絵バッチは漫画バッチとは別に、`.env` の挿絵専用変数を参照する。

```dotenv
MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT=grok_pro
MONOCRI_ILLUSTRATION_MODEL_DEFAULT=
MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT=book_cover
MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT=2k
```

優先順位は CLI `--provider` / `--model` / `--aspect-ratio` / `--resolution` > `.env` の `MONOCRI_ILLUSTRATION_*` > ツール既定。`MONOCRI_ILLUSTRATION_MODEL_DEFAULT` が空なら provider 側の `default_model` を使う。

## provider別 prompt formatter

`image_provider_novel_illustration_batch.py` は `config/image_generation.json` の `providers.*.prompt_formatter` を読み、provider に応じてプロンプト形式を切り替える。

- Forge / NovelAI: `tag_csv`（従来タグ列 + native negative_prompt）
- Grok / Grok Pro / OpenAI / OpenRouter: `natural_sections`（`Composition` / `Characters` / `Lighting and Mood` / `Do not include`）

Grok / OpenAI 系では `negative_prompt` を API に送らず、`Do not include:` へ統合する。比較実験時は CLI `--prompt-formatter` で上書きできる。

## チャットの最小トリガー

```text
本文から挿絵タグを作成してください。
```

対象を絞る場合:

```text
novels/NNN_作品名/_novel_text/novel_text01.md を参照して、第1章の挿絵IRを作成してください。
```

## 必須チェック

- `meta.intent: illustration` になっている。
- `scene.location_en` が非空で、必要な `*_en` が入っている。
- `render_instruction.prompt_header` / `panel_policy` / `character_policy` が入り、YAML単体で作画依頼として読める。
- `manga.panel_layout` が、漫画の段組ではなく挿絵の空間配置・枠線方針を説明している。
- `panels[]` が1件以上あり、各セルの `subjects[]` / `composition` / `camera` / `lighting` が具体的である。
- 枠線を使わない場合は、`manga.panel_layout`、`technical.negative_tags`、または `render_instruction.user_directives.defaults.omit_prompt_tags` で方針が分かる。

## 関連

- `manga-prompt-ir`: 共通スキーマ・キャラクター継承・タグ生成の基本
- `manga-tag-character-sync`: キャラクター固定外見の継承確認
- `image-provider`: 画像生成 provider への dry-run と本番実行
