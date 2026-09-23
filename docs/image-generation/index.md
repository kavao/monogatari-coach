# Image Generation

Image Provider は、Forge WebUI / NovelAI / Grok / OpenAI / OpenRouter などの provider へプロンプトを渡し、画像ファイルとメタ情報を保存する運用です。

画像生成全体の呼称とコマンド例では `image_provider_*` を使います。`provider=forge` は引き続き Forge WebUI を指す正式な provider 名です。

## 関連ファイル

- 実行クライアント: [`/tools/image_provider_generate.py`](../../tools/image_provider_generate.py)
- 既存画像のImage2Imageリライト: [image-provider-edit.md](image-provider-edit.md)
- 漫画ページ一括生成: [`/tools/image_provider_novel_manga_batch.py`](../../tools/image_provider_novel_manga_batch.py)
- キャラタグ一括生成: [`/tools/image_provider_novel_tag_batch.py`](../../tools/image_provider_novel_tag_batch.py)
- 設定: [`/config/image_generation.json`](../../config/image_generation.json)
- 環境変数テンプレート: [`/.env.example`](../../.env.example)
- 詳細スキル: [`image-provider`（旧 `forge-txt2img`）](../../.rulesync/skills/forge-txt2img/SKILL.md)
- 漫画ページ IR・検証・パイプライン: [manga-prompt-ir.md](manga-prompt-ir.md)
- 写植と領域合成（ローカル）: [manga-page-edit.md](manga-page-edit.md)
- 互換 Step1/Step2・タグ生成テンプレ: [manga-tag-generation.md](manga-tag-generation.md)
- 挿絵・表紙 IR・バッチ生成: [illustration-prompt-ir.md](illustration-prompt-ir.md)
- Step2 編集時の必読チェック（創作技法・`_how_to`）: [`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)

---

## provider の一覧と使い分け

`config/image_generation.json` の `providers` に登録されている provider は次のとおりです。

| provider | モデル | 主な用途 |
|----------|--------|---------|
| `forge` | UI で読み込んだ Checkpoint（SDXL / Flux） | ローカルコマ生成 |
| `novelai` | 既定 `nai-diffusion-5-full`。Curated は `v5-curated`。Vibe は `v4-5-full` | コマ生成（クラウド） |
| `grok` | `grok-imagine-image-2.0` | キャラタグ一括・単体画像・背景資料生成（background-concepts） |
| `grok_pro` | `grok-imagine-image-2.0` | 漫画ページ生成（step1-pages / step2-pages）・表紙/挿絵。1.0 は `--model standard`、quality slug は `--model quality` |
| `openai` | `gpt-image-2`（旧 `gpt-image-1.5` も明示指定可） | ページ生成の代替 |
| `openrouter` | `google/gemini-2.5-flash-image` など | OpenRouter 経由の画像生成 |

`grok` と `grok_pro` は同じ xAI API エンドポイントを使いますが、`config/image_generation.json` の `default_model` が異なります。ツール内部では同系として扱います。`grok_pro` は provider 名の互換名です。

`grok-imagine-image-pro` は 2026-05-15 退役対象で、quality slug へ寄せています。**quality slug は 2026-11-02 に退役**し、以後の同名要求は `grok-imagine-image-2.0` の `quality=low` で処理されます。このリポジトリの `grok` と `grok_pro` の既定 model は 2.0 です。

xAI の画像生成は `resolution: 1k / 2k` と `aspect_ratio` を受け付けます。代表 preset は `square` = `1:1`、`portrait` / `manga_b5_portrait` = `3:4`、`book_cover` / `cover_portrait` = `2:3`、`story_vertical` = `9:16`、`landscape` / `wide` = `16:9` です。2.0 は `21:9` / `5:2` も受けます。

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

# 漫画精密ページ生成 (--source step1-pages)  ← 既定: grok_pro（model は grok-imagine-image-2.0）
MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro

# 漫画ページ生成 (--source step2-pages)  ← 既定: grok_pro（同上）
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

Vibe Transfer は NovelAI V5 では未提供です。参照画像があるジョブは、`model` を省略すると自動で `nai-diffusion-4-5-full` になります。V5 を明示したまま参照を付けるとエラーになります。通常のコマ生成（参照なし）の既定は `nai-diffusion-5-full` です。

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

#### 困ったとき

- 「Vibe Transfer は NovelAI V5 では未提供」と出るときは、参照画像付きジョブに V5 を明示しています。`model` を `v4-5-full` にするか、参照を外します。
- 通常のコマ生成で V4.5 に戻したいときは、params または CLI で `model` を `v4-5-full` にします。
- HTTP 500 だけが返るときは、`uc_preset` を 4（Heavy）以上にし、`v4_prompt` が付いているか `--dry-run` で確認します。

### xAI / Grok

`provider=grok` または `provider=grok_pro` を使う場合は、`.env` の `XAI_API_KEY` に xAI Console の API キーを入れます。

`grok` と `grok_pro` の既定 model は `grok-imagine-image-2.0` です。1.0 に戻すときは `--model standard`、quality slug は `--model quality`（2026-11-02 退役予定）です。quality の config 既定は無く、省略するとリクエストに `quality` を載せず、API の auto（生成は low、編集は medium）になります。固定するときは `--grok-image-quality low` または `medium` です（CLI では `auto` も受けますが、並び比較には使いません）。優先順位は model が CLI > params JSON > config 既定、quality が CLI > params JSON > 未指定です。OpenAI や NovelAI に `--grok-image-quality` を付けるとエラーになります。

`--dry-run` では `resolved_model` が出ます。本番後のメタ JSON では `response_model` で実際にサーブしたモデルを確認できます。

2K の目安料金（公式、比較用）: quality slug $0.07、2.0 low $0.06、2.0 medium $0.08。入力画像は 1 枚ごとに課金されます。

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

`novelai_pipe` の既定は `input` への連結です。params に `split_pipe_characters: true` を付けると、左側が `base_caption`、右側以降が `char_captions` になります。位置は `centers` または `character_prompts[].center`（0–1、または A1–E5）で指定します。漫画 YAML には座標フィールドを足していません。例は `tools/fixtures/novelai_v5_chars_params.example.json` です。

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

### Grok の縦横比とプロンプト上限

`image_provider_novel_manga_batch.py` で **provider=grok_pro** かつ `--aspect-ratio` 未指定のとき、縦横比は次の順で決まります。

1. CLI `--aspect-ratio`
2. `.env` の `MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO`（例: `manga_b5_portrait` → `3:4`）
3. コード既定: `manga_b5_portrait`（`1:1` には落ちない）

`--dry-run` 実行時に `aspect_ratio: ...` 行が出ていれば、設定が正しく渡っています。

プロンプトが長くなりすぎた場合（step1-pages / step2-pages で日本語が多いとき）、`config/image_generation.json` の `max_prompt_bytes`（既定 7800）が効きます。これは **公式上限そのものではなく、リポジトリ内の暫定ゲート** です。経路は次のとおりです。

- **legacy formatter**: 従来どおり圧縮できます。`--dry-run` で圧縮後のバイト数を確認できます。
- **PageRenderPlan compiler**: 7800 bytes を超えたら黙って切らず、組み立て時点で停止します。

2.0 でも同じゲートを使います。

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

# 全ジョブの positive 先頭へタグ追加（試行用。本番前に dry-run で prompt を確認）
python tools/image_provider_novel_tag_batch.py novels/<作品> \
  --prepend-tags solo simple_background --dry-run
```

**タグの前後追加とマスク**（`prepend_tags` → 固定タグ → `danbooru_tags` → `append_tags` → `replace_tags` → `omit_tags`）:

| 層 | 指定 |
|----|------|
| 作品 | `_meta.yaml` の `character_tag_batch`（`omit_tags` / `replace_tags` 含む） |
| キャラ | `tag/characters/<id>.yaml` の `tag_batch`（任意） |
| CLI | `--prepend-tags` / `--append-tags` / `--omit-tags` / `--replace-tag OLD=NEW`（その実行のみ） |

マスクは YAML IR を変えず、生成直前のプロンプトにだけ効きます。negative も同様に `prepend_negative_tags` / `append_negative_tags`（YAML・CLI・`_meta.yaml`）。詳細は [tools/index.md](../tools/index.md) の `image_provider_novel_tag_batch.py` 節。

**漫画コマ（step1-panels）のマスク**: 同じ `omit_tags` / `replace_tags` を `image_provider_novel_manga_batch.py` でも使えます。`_meta.yaml` の `manga_tag_batch` が優先で、無ければ `character_tag_batch` を下敷きにします。CLI は `--omit-tags` / `--replace-tag`（step1-panels のみ）。

**挿絵・表紙のマスク**: `image_provider_novel_illustration_batch.py` でも同じ規則を使えます。`_meta.yaml` の `illustration_tag_batch` が優先で、無ければ `character_tag_batch` を下敷きにします。CLI は `--omit-tags` / `--replace-tag`。

dry-run の出力で `provider: grok_pro` / `jobs: 4` / `prepend_tags: ...` / `replace_tags: ...` / `omit_tags: ...` などを確認し、ユーザーの「OK」「進めて」などの承認後に `--dry-run` を外して本番実行します。

---

## 名前付きレシピ（`workflows`）

`_meta.yaml` に `workflows` セクションを書いておくと、8個のフラグを毎回手組みせずにレシピ名1つで呼び出せます。

```yaml
# _meta.yaml
workflows:
  manga_step1_default:
    source: step1-panels
    omit_panel_background: true
    color_mode: full_color
    novelai_portion_id: cross_flat
    strength: 1.0
    information_extracted: 1.0

  manga_step1_soft:
    source: step1-panels
    omit_panel_background: true
    color_mode: full_color
    novelai_portion_id: cross_flat
    strength: 0.5        # ポーション薄め
    information_extracted: 0.5
```

```bash
# 登録されているレシピ名を確認する
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 --list-workflows

# レシピで dry-run → 承認後に本番
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --workflow manga_step1_soft --dry-run

python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --workflow manga_step1_soft
```

**優先順位**: CLI 明示フラグ > `--workflow` 設定 > `.env` / 既定値

`--workflow` を使いつつ一部だけ上書きする例:

```bash
# レシピ適用 + provider だけ CLI で強制上書き
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --workflow manga_step1_default --provider forge --dry-run
```

雛形は `_how_to.example/_meta.yaml.example` の `workflows` 節を参照してください。

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

### 漫画精密ページ生成（step1-pages / grok_pro）

既定 model は `grok-imagine-image-2.0` です。品質を固定するときは `--grok-image-quality` を付けます。`--dry-run` で `resolved_model` を確認してから本番実行します。`--dry-run` を先に行うのは、API 課金が発生する前に内容を確認するためです。

```bash
# 確認（dry-run）— 既定 2.0。provider・resolved_model・保存先を表示する
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages --provider grok_pro \
  --aspect-ratio manga_b5_portrait --resolution 2k --dry-run

# 確認（dry-run）— Imagine 2.0 medium。--provider grok_pro を付け、--model v2 が 2.0 実名へ解決する
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages --provider grok_pro \
  --aspect-ratio manga_b5_portrait --resolution 2k \
  --model v2 --grok-image-quality medium --dry-run

# 本番実行（承認後。--dry-run を外す。既定 2.0 の例）
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages --provider grok_pro \
  --aspect-ratio manga_b5_portrait --resolution 2k
```

実行後、`manga/_assets/manga_01/comic/` に画像とメタ JSON が保存されます。2.0 本番では JSON の `response_model` が `grok-imagine-image-2.0` になります。

### 漫画ページ生成（step2-pages / grok_pro）

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

# OpenAIで縦長ページを指定（manga_b5_portrait は 1024x1536 へ解決）
python tools/image_provider_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider openai \
  --aspect-ratio manga_b5_portrait --dry-run

# サイズを直接指定する場合（--size が --aspect-ratio より優先）
python tools/image_provider_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider openai \
  --size 864x1536 --dry-run
```

OpenAIの漫画batchは、`--aspect-ratio` を指定しない限り `1024x1024` です。主なpresetは `manga_b5_portrait` / `portrait` / `book_cover` = `1024x1536`、`story_vertical` = `864x1536`、`landscape` / `wide` = `1536x864` です。dry-runの `image_size` で解決後の `size` を確認してから本番実行します。

**provider間の比率差に注意**: 同じ `manga_b5_portrait` でも、OpenAIは `1024x1536`（2:3）、Grok / OpenRouterは `3:4` です。Grok / OpenRouterと同じ3:4でOpenAIを比較するときは `--aspect-ratio 3:4`（`1024x1344`）を指定します。旧 `gpt-image-1.5` は明示指定できますが、GPT Image 2向けの任意サイズがAPI側で受理されるとは限らないため、比較時はサイズとモデルを揃えてください。

### OpenRouterでPageRenderPlanを使う

OpenRouterの新しいページcompilerを使う場合は、`--page-compiler page_render_plan`を明示します。legacyのOpenRouterページ生成は従来どおりです。新compilerは専用のImage APIを使い、Schema 1.1の参照画像を宣言順で渡します。

```bash
# 確認（dry-run）— provider・resolved_model・/images・文字方針・参照件数を表示
python tools/image_provider_novel_manga_batch.py tools/manga_prompt_ir/examples/p4_compare \
  --manga-stem manga_01 --source step1-pages --provider openrouter \
  --page-compiler page_render_plan --text-mode letter_later \
  --aspect-ratio manga_b5_portrait --dry-run
```

新compiler用の既定modelは `providers.openrouter.page_default_model`、legacy用は `providers.openrouter.default_model` です。APIキーの有効性をdry-runだけで確認することはできません。本番実行はdry-runの内容を確認してから行います。

### Forge の疎通確認

```bash
python tools/image_provider_generate.py --probe --provider forge
```

### OpenRouter

`OPENROUTER_API_KEY` には、OpenRouter の通常の API Key を設定します（Management API Key では `HTTP 401: User not found` になります）。

legacyの単体生成は `/chat/completions` を使います。漫画の `page_render_plan` は `/images` と `input_references` を使うため、利用modelがOpenRouterのImage Models APIで画像出力・参照入力に対応していることを確認してください。

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
| `nano_banana_2` | `google/gemini-3.1-flash-image` |
| `nano_banana_2_preview` | `google/gemini-3.1-flash-image-preview` |
| `nano_banana_pro` | `google/gemini-3-pro-image-preview` |
| `gpt_image_2` | `openai/gpt-image-2` |

PageRenderPlanでは、モデルprofileに応じて送信項目が変わります。Nano Banana 2は `resolution`、GPT Image 2は `quality` を使います。参照画像の上限はprofileで検証し、超過時は切り捨てず停止します。OpenRouterのImage Models APIは提供modelとendpointごとの対応パラメータを更新するため、利用modelを変更する場合はprofileとdry-runを確認します。

GPT Image 2を指定する場合は、次のようにqualityを明示できます。

```powershell
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 `
  --manga-stem manga_01 --source step1-pages --provider openrouter `
  --page-compiler page_render_plan --aspect-ratio manga_b5_portrait `
  --model gpt_image_2 `
  --image-quality medium --dry-run
```

漫画バッチは `--aspect-ratio` を省略するとOpenRouterでは `1:1` になります。比較・本番前確認では `manga_b5_portrait`（`3:4`）などを明示してください。dry-runでは `aspect_ratio`、`resolved_model`、`openrouter_profile`、`image_quality` または `image_resolution` を確認できます。`resolution` と `quality` を同時に送らないため、モデル比較ではそれぞれ別のdry-runを行います。

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
