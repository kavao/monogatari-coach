# Image Generation

Image Provider は、Forge WebUI / NovelAI / Grok / OpenAI / OpenRouter などの provider へプロンプトを渡し、画像ファイルとメタ情報を保存する運用です。

画像生成全体の呼称とコマンド例では `image_provider_*` を使います。`provider=forge` は引き続き Forge WebUI を指す正式な provider 名です。

## 関連ファイル

- 実行クライアント: [`/tools/image_provider_generate.py`](../../tools/image_provider_generate.py)
- 漫画ページ一括生成: [`/tools/image_provider_novel_manga_batch.py`](../../tools/image_provider_novel_manga_batch.py)
- キャラタグ一括生成: [`/tools/image_provider_novel_tag_batch.py`](../../tools/image_provider_novel_tag_batch.py)
- 設定: [`/config/image_generation.json`](../../config/image_generation.json)
- 環境変数テンプレート: [`/.env.example`](../../.env.example)
- 詳細スキル: [`image-provider`（旧 `forge-txt2img`）](../../.rulesync/skills/forge-txt2img/SKILL.md)
- 漫画ページ IR・検証・パイプライン: [manga-prompt-ir.md](manga-prompt-ir.md)
- 互換 Step1/Step2・タグ生成テンプレ: [manga-tag-generation.md](manga-tag-generation.md)
- Step2 編集時の必読チェック（創作技法・`_how_to`）: [`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)

---

## provider の一覧と使い分け

`config/image_generation.json` の `providers` に登録されている provider は次のとおりです。

| provider | モデル | 主な用途 |
|----------|--------|---------|
| `forge` | UI で読み込んだ Checkpoint（SDXL / Flux） | ローカルコマ生成 |
| `novelai` | `nai-diffusion-4-5-full` など | コマ生成（クラウド） |
| `grok` | `grok-imagine-image`（standard） | キャラタグ一括・単体画像・背景資料生成（background-concepts） |
| `grok_pro` | `grok-imagine-image-quality` | 漫画ページ生成（step1-pages / step2-pages）・表紙/挿絵の高品質生成 |
| `openai` | `gpt-image-1.5` など | ページ生成の代替 |
| `openrouter` | `google/gemini-2.5-flash-image` など | OpenRouter 経由の画像生成 |

`grok` と `grok_pro` は同じ xAI API エンドポイントを使いますが、`config/image_generation.json` の `default_model` が異なります。ツール内部では `_GROK_FAMILY = {"grok", "grok_pro"}` として同系として扱います。`grok_pro` は provider 名の互換名として残し、中身は xAI の現行高品質画像モデル `grok-imagine-image-quality` を指します。

`grok-imagine-image-pro` は xAI の 2026-05-15 退役対象です。古い設定から移行する場合は `grok-imagine-image-quality` を使います。

xAI の画像生成は `resolution: 1k / 2k` と `aspect_ratio` を受け付けます。代表 preset は `square` = `1:1`、`portrait` / `manga_b5_portrait` = `3:4`、`book_cover` / `cover_portrait` = `2:3`、`story_vertical` = `9:16`、`landscape` / `wide` = `16:9` です。

---

## .env の provider 既定値

`--provider` を省略したとき、バッチツールは `.env` の下記変数を参照します。

```dotenv
MONOCRI_ENV_VERSION=2026-05-16

NOVELAI_ACCESS_TOKEN=
XAI_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=

# キャラクタータグ一括生成 (image_provider_novel_tag_batch.py)
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai

# 漫画コマ生成 (--source step1-panels)
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=novelai

# 漫画精密ページ生成 (--source step1-pages)  ← 既定: grok_pro
MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro

# 漫画ページ生成 (--source step2-pages)  ← 既定: grok_pro
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok_pro

# 漫画背景概念生成 (--source background-concepts)
MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT=grok

# 挿絵・表紙生成 (image_provider_novel_illustration_batch.py)
MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT=grok_pro
MONOCRI_ILLUSTRATION_MODEL_DEFAULT=
MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT=book_cover
MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT=2k

# Forge のモデル族 (sdxl / flux)
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=

# 漫画バッチ (image_provider_novel_manga_batch.py) のみ。provider=grok_pro かつ
# コマンドに --aspect-ratio を付けないとき、Grok の既定（多くは config の 1:1）の代わりに使う。
# 例: manga_b5_portrait（3:4） / story_vertical（9:16） / 3:4 など
MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO=

# 漫画ページの色モード既定（monochrome / limited_color / full_color）
# ページYAMLの color_palette.mode が無いときのフォールバック。
MONOCRI_MANGA_COLOR_MODE_DEFAULT=monochrome
```

優先順位: CLI `--provider` > `.env` 用途別変数 > `config/image_generation.json` の `default_provider`

**漫画バッチの縦横比**: CLI `--aspect-ratio` が **最優先**。未指定かつ実際のプロバイダが `grok_pro` のときだけ `MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO` が `aspect_ratio_preset` に効く（それ以外のプロバイダでは無視）。

**漫画ページの色モード**: 優先順位は CLI `--color-mode` > ページYAMLの `color_palette.mode` > `.env` の `MONOCRI_MANGA_COLOR_MODE_DEFAULT` > スキーマ既定 `monochrome`。`--color-mode` はその実行だけの上書きで、YAML を自動変更しません。`novel_prompt_ir_validate.py` は `color_palette.mode` と `manga.visual_tags` / `render_instruction` の矛盾を WARNING として出しますが、センターカラーや扉絵だけカラーなどの例外を想定し、通常運用では自動修正・通常エラー化しません。

**挿絵バッチの既定値**: `image_provider_novel_illustration_batch.py` は CLI 未指定時に `MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT`、`MONOCRI_ILLUSTRATION_MODEL_DEFAULT`、`MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT`、`MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT` を参照します。既定は表紙・章扉を想定して `grok_pro`、`book_cover`（2:3）、`2k` です。モデル名は空なら provider の `default_model` を使います。

**不足確認**: `.env.example` の更新後は `python tools/env_check.py` を実行します。`MONOCRI_ENV_VERSION` の不一致、新しいキーの不足、選択中 provider に必要な API キー不足をまとめて表示します。

---

## provider別 prompt formatter

`config/image_generation.json` の `providers.*.prompt_formatter` で、同じ YAML IR を provider ごとに違う形へ整形します。

| formatter | 主な provider | 形式 |
|-----------|---------------|------|
| `tag_csv` | Forge / NovelAI | 従来のカンマ区切りタグ列 + native `negative_prompt` |
| `novelai_pipe` | NovelAI の漫画コマ生成 | `base | character A | character B` |
| `natural_sections` | Grok / OpenAI / OpenRouter の挿絵・表紙 | `Composition / Characters / Lighting / Do not include` |
| `manga_page_instruction` | Grok / OpenAI / OpenRouter のページ生成 | `Page goal / Layout / Panels / Character anchors / Do not include` |
| `background_brief` | 背景資料生成 | `Environment / Camera / Lighting / Mood` |

挿絵/表紙バッチでは `--prompt-formatter` で一時上書きできます。Grok / OpenAI 系では `negative_prompt` を API に送らず、`Do not include:` セクションへ統合します。

---

## 漫画生成の運用

### 生成モードとプロバイダの対応

| モード | オプション | 既定 provider | 説明 |
|--------|-----------|--------------|------|
| コマ生成 | `--source step1-panels` | `novelai` | 各コマを別画像として出力 |
| 精密ページ生成 | `--source step1-pages` | `grok_pro` | Step1 の詳細情報を保ったまま 1 ページ 1 枚で出力 |
| ページ生成 | `--source step2-pages` | `grok_pro` | Step2 のレイアウト要約から 1 ページ 1 枚で出力 |
| 背景概念生成 | `--source background-concepts` | `grok` | 人物なしの背景・空間設計を先出し |

Forge / NovelAI はコマ生成向け。step1-pages / step2-pages の正式対応先は `grok_pro` / `openai`。background-concepts は本番コマではなく背景資料生成として扱い、既定 provider は `grok`。

### 背景資料生成（background-concepts）

コマ絵・ページ絵を描く前に、場所・光源・構図・物品配置を固めるための背景資料画像を生成します。人物を主役にせず、空間設計を先に確定することで、後続のコマ生成・ページ生成の参照素材になります。

チャットへの指示:

```text
漫画ページの背景資料を生成してください。
```

Monogatari Coach は `--dry-run` で内容を提示してから、承認を受けて本番実行します。

**技術仕様:**

- 入力: `manga/pages/*.yaml` の `background_concepts[]`
- 出力分類: `backgrounds`
- 保存先: `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/`
- ファイル接頭辞: `<manga_stem>_p<page>_<concept_id>`
- 既定 provider: `grok`（`.env` の `MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT` があれば優先）
- 後続利用: 採用した場所・光・小道具・構図を YAML の `scene` / `background_concepts[]` / `render_instruction` へ書き戻す

複数視点を作る場合は `concept_id` に `establishing` / `wide` / `close` / `reverse` / `overhead` などの視点語を含めると、メタ情報と画像ファイルを追跡しやすいです。

### Grok のプロンプト上限と自動圧縮

Grok API のプロンプト上限は **UTF-8 バイト数**で管理されています（日本語 1 文字 ≒ 3 バイト）。

`config/image_generation.json` の `providers.grok_pro.max_prompt_bytes`（既定 `7800`）が設定されていると、`image_provider_novel_manga_batch.py` が step1-pages のプロンプトを自動圧縮します。

圧縮フェーズ（上限に収まった時点で停止）:

1. `render_instruction` ブロック行を除去
2. `- tag:` 行（キャラ固定タグ列）を除去
3. `- 日本語訳:` 行を除去
4. バイト数ベースの末尾切り捨て + `[...省略]`

---

## 生成前の確認フロー（必須）

画像生成を実行する前に、必ず次の順で確認します。

1. **`.env` を確認** — 使用プロバイダと API キーが設定されているか
2. **`config/image_generation.json` を確認** — ファイルが存在するか
3. **Forge の場合のみ** — UI の Checkpoint と `active_model_family`（sdxl / flux）が一致しているか
4. **`--dry-run` を実行してユーザーに確認を取る** — プロバイダ名・モデル・ジョブ数・保存先を示し、承認を得てから本番実行する

```bash
# dry-run 例（漫画精密ページ生成）
python tools/image_provider_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --dry-run

# dry-run 例（キャラタグ一括）
python tools/image_provider_novel_tag_batch.py novels/<作品> --dry-run
```

dry-run の出力で `provider: grok_pro` / `jobs: 4` などを確認し、ユーザーの「OK」「進めて」などの承認後に `--dry-run` を外して本番実行します。

---

## よく使うコマンド

### キャラタグ一括生成

```bash
# dry-run（provider 確認）
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --dry-run

# 本番
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター
```

### 漫画コマ生成（step1-panels / novelai）

```bash
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-panels --dry-run

python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-panels
```

### 漫画精密ページ生成（step1-pages / grok_pro = quality）

```bash
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k --dry-run

python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k
```

### 漫画ページ生成（step2-pages / grok_pro = quality）

```bash
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k --dry-run

python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k
```

### provider を明示して上書き

```bash
# grok_pro を明示
python tools/image_provider_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider grok_pro

# openai を使う
python tools/image_provider_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider openai
```

### Forge の疎通確認

```bash
python tools/image_provider_generate.py --probe --provider forge
```

### OpenRouter

OpenRouter 経由の画像生成は、OpenRouter の `/api/v1/chat/completions` に `modalities: ["image", "text"]` と `image_config` を渡す方式です。画像は `choices[].message.images[].image_url.url` に base64 data URL として返ります。利用できる画像モデルは OpenRouter Models API の `output_modalities=image` で確認します。

`OPENROUTER_API_KEY` には、OpenRouter の通常の API Key を設定します。Management API Key は `/api/v1/keys` などの管理APIには使えますが、`/api/v1/chat/completions` には使えないため、`HTTP 401: User not found` になることがあります。

```bash
python tools/image_provider_generate.py \
  --params tools/fixtures/openrouter_params.nano_banana.example.json --dry-run

python tools/image_provider_generate.py \
  --params tools/fixtures/openrouter_params.gpt_image_2.example.json --dry-run
```

設定済み alias:

| alias | OpenRouter model ID |
|-------|---------------------|
| `nano_banana` | `google/gemini-2.5-flash-image` |
| `nano_banana_2` | `google/gemini-3.1-flash-image-preview` |
| `nano_banana_pro` | `google/gemini-3-pro-image-preview` |
| `gpt_image_2` | `openai/gpt-5.4-image-2` |

2026-05-06 時点の OpenRouter `output_modalities=image` 一覧では、Grok Imagine 相当の model ID は確認できていません。追加された場合は `config/image_generation.json` の `providers.openrouter.model_aliases` に alias を足します。

---

## 画像の保存先

| 種別 | 保存先 |
|------|--------|
| 漫画ページ / コマ | `novels/<作品>/manga/_assets/<manga_XX>/`（**章 `manga_XX` 直下が標準。ページ別サブフォルダは推奨しない**） |
| 挿絵 / 表紙 | `novels/<作品>/illustrations/_assets/<illustration_XX>/` |
| キャラクター立ち絵 | `novels/<作品>/tag/<romaji>/` |

コマ画像は同一フォルダ内で `file_prefix`（例: `manga_01_p02_k03`）により区別する。`image_provider_novel_manga_batch --subdir-by-page` は例外的な用途のみ。

フォルダ一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N`。挿絵は `illustrations/pages/illustration_XX_pYY.yaml` から `illustrations/_assets/illustration_XX/` を作成する。

---

## 参考

- プロバイダ詳細・Flux 固有パラメータ: [`image-provider`（旧 `forge-txt2img`）](../../.rulesync/skills/forge-txt2img/SKILL.md)
- ワークフロー全体: [`.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md)
