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
- 挿絵・表紙 IR・バッチ生成: [illustration-prompt-ir.md](illustration-prompt-ir.md)
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

## API キーの取得先

API キーやトークンは `.env` に保存します。公開リポジトリ、チャット、スクリーンショットに貼らないでください。

### NovelAI

`provider=novelai` を使う場合は、`.env` の `NOVELAI_ACCESS_TOKEN` に NovelAI の Persistent API Token を入れます。

NovelAI 公式ドキュメントでは、User Settings の Account 画面にある **Get Persistent API Token** から API 用トークンを取得できます。新しいトークンを生成すると古いトークンは無効になるため、既に別ツールで使っている場合は更新漏れに注意します。

- 公式: [NovelAI Account settings](https://docs.novelai.net/en/text/usersettings/account/)
- `.env`:

```dotenv
NOVELAI_ACCESS_TOKEN=取得したPersistent API Token
```

### NovelAI Vibe Transfer

`tools/image_provider_generate.py` の NovelAI provider は、Vibe Transfer / ポーション用に `reference_image_paths` または `reference_image_multiple` を受け付けます。

- `reference_image_paths`: PNG / JPEG / WEBP / `.naiv4vibe` / `.naiv4vibeBundle` のパス配列。`.naiv4vibe` / `.naiv4vibeBundle` は、ファイル内の `encodings.*.encoding` を優先して NovelAI API へ渡します。画像を含む形式なら画像も読み込みます。
- `reference_image_multiple`: 画像をbase64化した文字列配列。`data:image/...;base64,` 付きでも受け付けます。
- `reference_information_extracted_multiple`: 各参照の Information Extracted。**スカラー**のときはバンドル内 `importInfo` への乗数（省略時 `1.0`）。**配列**のときはスロットごとの絶対値。
- `reference_strength_multiple`: 各参照の Reference Strength。**スカラー**のときはバンドル内 `importInfo.strength` への乗数（省略時 `1.0`）。**配列**のときはスロットごとの絶対値。`.naiv4vibebundle` の `vibes[]` ごとに `importInfo` を読み、比率を保ったまま乗算する。
- `normalize_reference_strength_multiple`: V4系の複数参照正規化。バンドル内メタで strength が複数値のときは比率維持のため自動で `false`。PNG 単体などは既定 `true`。

#### strength / IE の指定方式まとめ

| 入力方式 | `reference_strength_multiple` の扱い | `reference_information_extracted_multiple` の扱い |
|----------|--------------------------------------|---------------------------------------------------|
| **スカラー**（例: `0.5`） | バンドル内 `importInfo.strength` への乗数。バンドル内 vibe ごとの比率を保ったまま全件に適用。 | バンドル内 `importInfo.information_extracted` への乗数。 |
| **配列**（例: `[0.45, 0.6]`） | スロットごとの絶対値として直接送信。件数は `reference_image_multiple` の件数と一致が必要。 | スロットごとの絶対値。 |
| **省略**（指定なし） | スカラー乗数 `1.0` として動作（バンドル値をそのまま使用）。 | 同左。 |
| **base64 直指定**（`reference_image_multiple` に base64 のみ） | `importInfo` がないため、PNG 等のプレーン参照と同じ既定値（strength `0.6`）× スカラー乗数で件数補完。 | 既定値（IE `1.0`）× スカラー乗数で件数補完。 |

> **注意**: base64 直指定時にスロットごとの絶対値を使いたい場合は、`reference_strength_multiple` と `reference_information_extracted_multiple` を件数と同じ長さの配列で明示します。

#### params JSON 例

ポーションファイルを渡す場合:

```json
{
  "provider": "novelai",
  "prompt": "1girl, fantasy, detailed, cinematic lighting",
  "negative_prompt": "lowres, blurry, bad hands",
  "model": "nai-diffusion-4-5-full",
  "reference_image_paths": ["_how_to/image_refs/novelai/2026-05-17_flat.naiv4vibebundle"],
  "reference_information_extracted_multiple": [1.0],
  "reference_strength_multiple": [0.6],
  "normalize_reference_strength_multiple": true,
  "output_dir": "outputs/novelai",
  "file_prefix": "novelai_vibe",
  "count": 1
}
```

PNG / JPEG / WEBP を参照画像として使う場合も同じ `reference_image_paths` に指定します。

```json
{
  "provider": "novelai",
  "prompt": "1girl, fantasy, detailed",
  "negative_prompt": "lowres, blurry, bad hands",
  "model": "nai-diffusion-4-5-full",
  "reference_image_paths": ["outputs/references/style.png"],
  "reference_information_extracted_multiple": [1.0],
  "reference_strength_multiple": [0.6],
  "output_dir": "outputs/novelai",
  "file_prefix": "novelai_vibe",
  "count": 1
}
```

#### 実行手順

まず `--dry-run` で `reference_image_multiple` が入っていることを確認します。dry-run では長いbase64/encoding文字列は伏せ字表示になります。

```powershell
python tools/image_provider_generate.py --params path\to\novelai_vibe_params.json --dry-run
```

ユーザー承認後に本番実行します。本番は Anlas/API 消費が発生する可能性があります。

```powershell
python tools/image_provider_generate.py --params path\to\novelai_vibe_params.json
```

生成後は、`output_dir` に PNG と同名 JSON が保存されます。同名 JSON の `novelai_payload_request.parameters.reference_image_multiple` に、ポーションまたは参照画像由来の値が記録されます。

#### 調整目安

- `reference_strength_multiple` / `reference_information_extracted_multiple`（漫画バッチ・`.env`）: バンドル内 `importInfo` への**乗数**。基本は `1.0`（NovelAI UI エクスポート値どおり）。全体を薄めたいときは `0.5` など。
- バンドル内 vibe ごとの比率は維持される（例: 0.22 と 0.2 → 乗数 0.5 で 0.11 と 0.1）。
- スロットごとに絶対値を直接指定したいときは params JSON で配列 `[0.45, 0.6]` を渡す（乗数モードではない）。
- 係数は `0.01`〜`1.0` の範囲に自動 clamp されます。`0` を渡しても `0.01` として送信されます（API の不定挙動を回避するための下限）。

### xAI / Grok

`provider=grok` または `provider=grok_pro` を使う場合は、`.env` の `XAI_API_KEY` に xAI Console の API キーを入れます。

xAI 公式 Quickstart では、xAI アカウントを作成し、API Console の API Keys page でキーを発行して `XAI_API_KEY` として使う流れが示されています。利用にはクレジットやモデル利用条件が関係するため、料金・利用可能モデルは公式 Console と Pricing を確認してください。

- 公式: [xAI Quickstart](https://docs.x.ai/developers/quickstart)
- Console: [xAI API Console](https://console.x.ai/)
- `.env`:

```dotenv
XAI_API_KEY=取得したAPIキー
```

### OpenRouter

`provider=openrouter` を使う場合は、`.env` の `OPENROUTER_API_KEY` に OpenRouter の API キーを入れます。

OpenRouter 公式ドキュメントでは、API Keys 画面でキーを作成し、直接 API を呼ぶ場合は `Authorization: Bearer <API key>` として使う流れが示されています。OpenRouter のキーには任意で credit limit を設定できます。利用するモデルごとに料金・提供元・利用可否が異なるため、実行前に OpenRouter のモデルページとクレジット状況を確認してください。

- 公式: [OpenRouter Authentication](https://openrouter.ai/docs/api-reference/authentication)
- API keys: [OpenRouter Keys](https://openrouter.ai/keys)
- `.env`:

```dotenv
OPENROUTER_API_KEY=取得したAPIキー
```

設定後は、次で不足を確認します。

```bash
python tools/env_check.py
```

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
| コマ生成 | `--source step1-panels`（`--mode` でも可） | `novelai` | 各コマを別画像として出力 |
| 精密ページ生成 | `--source step1-pages`（`--mode` でも可） | `grok_pro` | Step1 の詳細情報を保ったまま 1 ページ 1 枚で出力 |
| ページ生成 | `--source step2-pages`（`--mode` でも可） | `grok_pro` | Step2 のレイアウト要約から 1 ページ 1 枚で出力 |
| 背景概念生成 | `--source background-concepts`（`--mode` でも可） | `grok` | 人物なしの背景・空間設計を先出し |

`image_provider_novel_manga_batch.py` では **`--source` が正式名**です。チャットやルールでいう「生成モード」と揃えるため **`--mode` は同じ値の別名**として使えます（例: `--mode step1-panels`）。

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

### Grok の縦横比と自動圧縮

`image_provider_novel_manga_batch.py` で **provider=grok_pro** かつ `--aspect-ratio` 未指定のとき、縦横比は次の順で決まります。

1. CLI `--aspect-ratio`
2. `.env` の `MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO`（例: `manga_b5_portrait` → `3:4`）
3. コード既定: `manga_b5_portrait`（`1:1` には落ちない）

`--dry-run` 実行時に `aspect_ratio: ...` 行が出ていれば、設定が正しく渡っています。

プロンプトが長くなりすぎた場合（step1-pages で日本語が多いとき）、`config/image_generation.json` の `max_prompt_bytes` に基づいて自動圧縮されます。圧縮が起きているかは `--dry-run` の出力で確認できます。

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

**背景を描かせない（背景資料と合成する前提）**

`--source step1-panels` のときだけ有効。舞台・場所・浴室設備・湯気などのタグをプロンプトから外し、`simple_background` 等を付与する。

```bash
python tools/image_provider_novel_manga_batch.py novels/066_作品名 \
  --manga-stem manga_01 --source step1-panels --omit-panel-background --dry-run
```

環境変数 `MONOCRI_MANGA_STEP1_OMIT_PANEL_BACKGROUND=1` でも同じ（CLI フラグが優先）。

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

`OPENROUTER_API_KEY` には、OpenRouter の通常の API Key を設定します（Management API Key では `HTTP 401: User not found` になります）。

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
| 漫画ページ / コマ | `novels/<作品>/manga/_assets/<manga_XX>/comic/`（**`comic/` 直下が標準。ページ別サブフォルダは推奨しない**） |
| 漫画・背景資料 | `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` |
| 挿絵 / 表紙 | `novels/<作品>/illustrations/_assets/<illustration_XX>/` |
| キャラクター立ち絵 | `novels/<作品>/tag/<romaji>/` |

コマ画像は同一フォルダ内で `file_prefix`（例: `manga_01_p02_k03`）により区別する。`image_provider_novel_manga_batch --subdir-by-page` は例外的な用途のみ。

フォルダ一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N`。挿絵は `illustrations/pages/illustration_XX_pYY.yaml` から `illustrations/_assets/illustration_XX/` を作成する。

---

## 参考

- ワークフロー全体: [Workflow](../workflow/index.md)
- ツールリファレンス: [Tools](../tools/index.md)
