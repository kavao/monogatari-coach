---
name: image-provider
description: >-
  Stable Diffusion Forge / NovelAI / Grok(xAI) / OpenAI Images API / OpenRouter などの画像 provider へ
  tools/image_provider_generate.py でプロンプトを渡し、画像を outputs または作品フォルダへ保存する。
  dry-run と計画提示の後はユーザー承認まで本番実行しない。本番後は保存先のファイル存在で完了を検証する。
targets: ["*"]
---

> 移行メモ: 旧スキル名 `forge-txt2img` と旧スクリプト名 `forge_*` は互換名として残す。新しい案内・運用名は **image-provider** / `image_provider_*` を使う。`provider=forge` は Forge WebUI を指す provider 名として継続する。

> 横断正本: 画像生成の承認・失敗時の provider 切替禁止・生成完了条件・生成モード用語は **`.rulesync/rules/concepts.md`** を正とする。このスキルは image-provider 作業での適用手順と provider 別の確認事項を扱う。

## 目的

`_how_to/manga_tag.md` / `manga.md` で **漫画タグ**、`_how_to/tag.md` で **キャラクタータグ**を用意した**あと**、同じプロンプト思想で **Forge / NovelAI / Grok / OpenAI** で画像を生成し、リポジトリ内の決めたフォルダにストックする。

v2 は **txt2img のみ**・`provider` で **`forge` / `novelai` / `grok` / `openai` / `openrouter`** を切り替える。既定は `config/image_generation.json` の **`default_provider`**。Forge は UI で読み込んだモデルに追従し、NovelAI は `.env` の **`NOVELAI_ACCESS_TOKEN`**、Grok は **`XAI_API_KEY`**、OpenAI は **`OPENAI_API_KEY`**、OpenRouter は **`OPENROUTER_API_KEY`** を使って REST API に接続する。

## プロバイダ解決の優先順位（LLM 向け確認手順）

> **⚠️ LLM 必須アクション（最初に行う）**
> 画像生成を案内・実行する前に、必ずプロジェクトルートの **`.env` を `Read` で開き**、実際に使うプロバイダと APIキーを確認する。
> `config/image_generation.json` の `default_provider: "forge"` はあくまでフォールバックであり、`.env` に設定がある場合は **`.env` が優先**される。
> `.env` を読まずに Forge の疎通確認（`--probe`）から始めると、設定済みの NovelAI / Grok / OpenAI を見落とす原因になる。

ユーザーが `--provider` を明示しない場合、バッチツールは次の順でプロバイダを決定する。

| 優先順 | 参照先 | 対象ツール・用途 |
|--------|--------|-----------------|
| 1 | CLI `--provider` | すべてのバッチ・単体生成 |
| 2 | `.env` の環境変数（下表） | バッチツールのデフォルト |
| 3 | `config/image_generation.json` の `default_provider` | フォールバック（既定 `forge`） |

### `.env` の環境変数（用途別）

| 環境変数 | 対象ツール・用途 |
|----------|-----------------|
| `MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT` | `image_provider_novel_tag_batch.py`（キャラタグ一括生成） |
| `MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT` | `image_provider_novel_manga_batch.py --source step1-panels`（コマ生成） |
| `MONOCRI_MANGA_STEP1_OMIT_PANEL_BACKGROUND` | `image_provider_novel_manga_batch.py --source step1-panels` で `--omit-panel-background` と同等（`1` / `true`） |
| `MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT` | `image_provider_novel_manga_batch.py --source step1-pages`（精密ページ生成。既定 `grok_pro`） |
| `MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT` | `image_provider_novel_manga_batch.py --source step2-pages`（ページ生成。既定 `grok_pro`） |
| `MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT` | `image_provider_novel_manga_batch.py --source background-concepts`（既定 `grok`） |
| `MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT` | `image_provider_novel_illustration_batch.py`（挿絵・表紙生成。既定 `grok_pro`） |
| `MONOCRI_ILLUSTRATION_MODEL_DEFAULT` | `image_provider_novel_illustration_batch.py` で provider に渡すモデル名または alias。空なら provider の `default_model` |
| `MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT` | `image_provider_novel_illustration_batch.py` の既定アスペクト。表紙向け既定は `book_cover`（2:3） |
| `MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT` | `image_provider_novel_illustration_batch.py` の既定解像度。Grok 向け既定は `2k` |
| `MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO` | `image_provider_novel_manga_batch.py` で **実際の provider が `grok_pro`** かつ **`--aspect-ratio` 未指定**のとき、`config` の Grok 既定アスペクト（多くは `1:1`）の代わりに使う（例: `manga_b5_portrait`, `3:4`）。CLI が最優先 |
| `MONOCRI_FORGE_MODEL_FAMILY_DEFAULT` | Forge の `active_model_family` を `.env` で上書きしたいとき |
| `MONOCRI_GROK_MODEL_TIER_DEFAULT` | `grok` provider の global モデル tier（`standard` / `quality` / 互換 `pro`）。`grok_pro` を直接使う運用では不要 |

### grok と grok_pro の使い分け

`config/image_generation.json` では Grok を **2つの provider エントリ**に分けて管理する。

| provider | 使用モデル | 主な用途 |
|----------|-----------|----------|
| `grok` | `grok-imagine-image`（standard） | キャラタグ一括生成など単体画像 |
| `grok_pro` | `grok-imagine-image-quality` | 漫画ページ生成（step1-pages / step2-pages）・表紙/挿絵の高品質生成 |

ツール内では `_GROK_FAMILY = frozenset({"grok", "grok_pro"})` として認識し、API 呼び出しは同じ xAI エンドポイントを共有する。プロバイダ名の違いが `config/image_generation.json` の `default_model` を切り替える唯一の手段であり、`MONOCRI_GROK_MODEL_TIER_DEFAULT` はオーバーライド手段として残すが、**漫画・挿絵の高品質生成向けは `grok_pro` を直接指定するほうが意図が明確**。

`grok_pro` は旧 provider 名との互換名として残す。xAI の `grok-imagine-image-pro` は 2026-05-15 退役対象のため、現在の `grok_pro.default_model` は `grok-imagine-image-quality` とする。

xAI の現行画像生成は `resolution: 1k / 2k` と `aspect_ratio` を受け付ける。`config/image_generation.json` では、表紙向けに `book_cover` / `cover_portrait` = `2:3`、漫画縦向けに `manga_b5_portrait` / `portrait` = `3:4`、縦長ストーリー向けに `story_vertical` = `9:16` を preset として持つ。

### provider別 prompt formatter

`config/image_generation.json` の `providers.*.prompt_formatter` で、生成前のプロンプト整形を provider ごとに切り替える。

| formatter | 主な用途 |
|-----------|----------|
| `tag_csv` | Forge / NovelAI 向けの従来タグ列 |
| `novelai_pipe` | NovelAI の漫画コマ向け `base | character` 形式 |
| `natural_sections` | Grok / OpenAI / OpenRouter の挿絵・表紙向け自然文 |
| `manga_page_instruction` | Grok / OpenAI / OpenRouter の漫画ページ向け自然文 |
| `background_brief` | 背景資料生成向け |

Grok / OpenAI 系は native `negative_prompt` を持たない、または効き方が異なるため、formatter 側で `Do not include:` に統合する。dry-run では `prompt_formatter` と `negative_mode` を確認する。

プロバイダが不明な場合は **`--dry-run`** でジョブ一覧とプロバイダを確認してから本番実行を案内する。

> **⚠️ ユーザー確認（必須）**
> プロバイダ・モデル・ジョブ数が確定したら、**`.rulesync/rules/concepts.md` の「画像生成: dry-run から本番まで」**に従い、`--dry-run` の結果提示とユーザー承認を挟んでから本番実行する。

## 小説執筆の「実行継続」との関係（画像生成は例外）

スキル **`novel-text-file-output`** の「ツール予告したら同一ターンでツール続行」は、**画像生成には適用しない**。`image_provider_generate.py`、`image_provider_novel_tag_batch.py`、`image_provider_novel_manga_batch.py` 等では、`--dry-run` の提示までで一度止め、ユーザーの明示承認後に本番実行する。

## エラー時の扱い（自動プロバイダ切り替え禁止）

HTTP 429 / 403 / 5xx などで失敗した場合は、**`.rulesync/rules/concepts.md` の「画像生成失敗時の provider 切替」**に従う。失敗した provider 名、代表エラー、影響範囲を報告し、別 provider への自動切替は行わない。

## 生成「完了」の定義（幻覚完了の防止）

ユーザーに「画像生成が完了した」「すべて出力した」と **完了扱い**で伝えてよい条件は、**`.rulesync/rules/concepts.md` の「完了扱い条件」**を正とする。要点は、ユーザー承認後の本番実行と、`--dry-run` で示した保存先での画像ファイル確認である。API 成功や exit code だけで完了扱いしない。

---

## 漫画生成の用語整理

生成モード用語の横断定義は **`.rulesync/rules/concepts.md` の「生成モード用語」**を正とする。このスキルでは、各モードで推奨する provider と実行コマンドを扱う。会話で明示がない場合は **コマ生成** とみなす。

## 推奨プロバイダ分担（Step1 コマ／ページ系）

本リポジトリの**既定の運用イメージ**は次のとおり。

| モード | `image_provider_novel_manga_batch.py` | 推奨プロバイダ | `.env` デフォルト変数 |
|--------|------------------------------|----------------|----------------------|
| **コマ生成（Step1）** | `--source step1-panels`（既定） | **NovelAI** / **Forge** / **OpenAI** | `MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=novelai` |
| **精密ページ生成** | `--source step1-pages` | **grok_pro** または **OpenAI** | `MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro` |
| **ページ生成** | `--source step2-pages` | **grok_pro** または **OpenAI** | `MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok_pro` |
| **背景概念生成** | `--source background-concepts` | **grok**（既定）または **OpenAI** | `MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT=grok` |

**Grok の分担ルール**: コマ単体（step1-panels）は **NovelAI / Forge** を基本とする。1ページを1枚にまとめる **step1-pages / step2-pages** は **`grok_pro`（qualityモデル）を既定**とする。**background-concepts** は本番コマではなく背景資料生成として扱い、既定は `.env` と docs に合わせて **`grok`** とする。

## 漫画生成の API 対応範囲（2026-05-16 時点）

- **コマ生成**:
  **Forge / NovelAI / Grok / OpenAI** に対応。
- **精密ページ生成**:
  **Grok / OpenAI** を正式対応とする。**Nanobanana は導入予定の想定対応先**。
- **ページ生成**:
  **Grok / OpenAI** を正式対応とする。**Nanobanana は導入予定の想定対応先**。
- **背景概念生成**:
  **Grok** を既定とし、必要に応じて **OpenAI** を選べる。YAML の `background_concepts[]` を入力にする。
- **固定特徴・状況タグの自動注入**:
  **`step1-panels` / `step1-pages` / `step2-pages`** では、作品フォルダの **`tag/*.md`** を参照し、本文に登場が見えるキャラごとに **状況に最も近い Danbooru Tags ブロック**を prompt へ自動注入する。本文側には **キャラ名** と、必要なら **オンボーディング / βテスト開始 / 緊急修復** などの状況語を明記しておくと安定しやすい。
- **注入のオフ（`--no-character-anchors`）**:
  **`tag/*.md` を読まず**、STYLE_PREFIX ＋ Step 本文のみを送る。使いどころの例: **Grok で step1-pages / step2-pages が拒否**するとき、または注入語を入れたくない実験時。**step1-panels を NovelAI で回す通常運用ではオフ不要**（上表「推奨プロバイダ分担」参照）。
- **背景を描かせない（`--omit-panel-background`）**:
  **`--source step1-panels` のみ**。YAML から舞台・場所・浴室・湯気などのタグを外し、`simple_background` 等を付与。先に **`background-concepts`** で出した背景資料と Photoshop 等で合成する前提。CLI または `MONOCRI_MANGA_STEP1_OMIT_PANEL_BACKGROUND=1`。
- **ページ生成の非対応**:
  **Forge / NovelAI** は、このスキルの既定運用では **step1-pages / step2-pages の正式対応先に含めない**。

## 前提（Forge）

- Forge / WebUI を **`--api` 付き**で起動する（これが無いと `/sdapi/v1/txt2img` が **HTTP 404** になり、Gradio の「Running on http://127.0.0.1:7860」だけでは足りないことがある）。
  - 例: `webui-user.bat` で `set COMMANDLINE_ARGS=--api` のあと起動。
- 疎通確認: `python tools/image_provider_generate.py --probe`（`/docs` と `/sdapi/v1/samplers` の結果を表示。**samplers が 404 なら --api なし**の可能性が高い）。
- 設定はリポジトリルートの **`config/image_generation.json`**（必須）。Forge / NovelAI / Grok の各 `providers.*` と **`default_provider`** をここで管理する。`tools/image_provider_generate.py` の **`--config`** で別ファイルを指すことはできるが、**リポジトリ運用上の正本はこのファイル**とする。
- **画像生成前**に UI の Checkpoint が FLUX / SDXL のどちらかと `active_model_family` を揃える（詳細は `.rulesync/rules/overview.md` の「画像生成（txt2img）の事前確認」）。

### Forge + Flux（ブラウザと API を揃える）

- **Checkpoint / VAE / テキストエンコーダは API ペイロードに含めない**。起動中の Forge に UI で読み込んだものがそのまま使われる（**ブラウザの設定と一致させる**）。
- **リポジトリ既定の `active_model_family` は `sdxl`**（`presets.sdxl`: CFG 約 7・Euler a・1024² など）。**Flux** で回すときは **`active_model_family` を `flux`** にし、`presets.flux`（CFG 約 1・Euler・Schedule Simple・Distilled CFG など）を使う。
- Forge は API 自体は `width` / `height` 指定だが、このリポジトリでは **`aspect_ratio_preset`** を受け付け、`providers.forge.aspect_ratio_presets` から **family ごとの寸法**へ展開する。`square`、`portrait`、`manga_b5_portrait`、`story_vertical`、`landscape`、`wide` を用意している。
- **Flux の Checkpoint なのに SDXL 向けの CFG（例: 7）のまま** txt2img を叩くと、画が壊れる・返却 PNG が極小になることがある。逆に **SDXL で CFG 1** だけではプロンプト追従が弱くなりやすい。
- API 拡張フィールド: **`scheduler`**（例: `Simple`）・**`distilled_cfg_scale`**（例: `3.5`）。`tools/image_provider_generate.py` が `image_generation.json` または params JSON から付与する。
- 例: `tools/fixtures/forge_params.flux.example.json`
- **VAE 未設定・誤った VAE** でも UI では見えて API でだけ失敗する、というケースは起こりうる。生成ログの `info` や Forge のコンソールも参照する。

## 前提（NovelAI）

- `.env.example` を `.env` にコピーし、**`NOVELAI_ACCESS_TOKEN`** を記入する。初回セットアップでは `howto_init.py` / `init.bat` が未作成時に自動コピーする。
- 設定は **`config/image_generation.json`** の `providers.novelai`。既定の通信先は `https://image.novelai.net/ai/generate-image`。
- params JSON か CLI で **`provider=novelai`** を選ぶ。
- 画像設定（steps / guidance / sampler など）の意味は NovelAI 公式ドキュメントの Image Generation 節に揃える。REST の詳細は公開仕様が薄いため、エンドポイントや追加フィールドが変わった場合は **config 側で吸収**する前提で運用する。
- **ベース | キャラクター（`|` 区切り）**: NovelAI のプロンプトで `|` を挟むと左をシーン・画風寄り、右をキャラ固長寄りに振りやすい。`tools/image_provider_generate.py` はプロンプトに `|` が含まれるとき **左側だけ**へ品質接尾辞（例: `rating:general`）を付与する。`tools/image_provider_novel_manga_batch.py` は **`provider=novelai` かつ YAML・`--source step1-panels`** のとき、漫画ページ IR から **`ベースタグ | キャラタグ`** を自動組み立てする（オフは `--no-novelai-pipe-character-tags`）。
- **互換 `manga/manga_XX.md` のエクスポート**: `tools/novel_prompt_ir_export_md.py` で **`--manga-page` を付けて `manga_XX.md` を生成するときは、エージェント・手動とも既定で `--novelai-pipe-tags` を付ける**（Step1 の `tag` 行を上記と同形式にする。**付けないと** Step1 がカンマ一列のみになり、NovelAI 運用とずれる）。キャラ互換のみ（`--manga-page` なし）では不要。Step2 ブロックの組み立てはこのフラグでは変わらないが、手順の一本化のため漫画出力では付けてよい。

## 前提（Grok / xAI）

- `.env` に **`XAI_API_KEY`** を記入する。
- 設定は **`config/image_generation.json`** の `providers.grok`。既定の通信先は `https://api.x.ai/v1/images/generations`。
- params JSON か CLI で **`provider=grok`** を選ぶ。
- 画像モデルは **`grok-imagine-image`**。`aspect_ratio`、`resolution`、`n`、`response_format` が公式に案内されている。
- このリポジトリでは `providers.grok.aspect_ratio_presets` により、`square`、`manga_b5_portrait`、`story_vertical` などの preset 名でも切り替えられる。**B5 実寸そのものは xAI の公式 ratio ではない**ため、`manga_b5_portrait` は **`3:4`** の近似 preset。
- 既定実装は **`response_format: "b64_json"`** で受け、URL の失効前にそのまま保存する。

### Grok プロンプト上限と自動圧縮（step1-pages で必須）

Grok の API は **プロンプトの上限が約 8000 UTF-8 バイト**（公式仕様は文字数ではなくバイト数）。日本語は 1 文字 3 バイトのため、YAML IR から組み立てた step1-pages プロンプト（`render_instruction` ＋ パネル詳細 ＋ キャラ固定タグ）は **4 ページ分すべてが上限を超えることが多い**。

`config/image_generation.json` の **`providers.grok.max_prompt_bytes`** にバイト上限（既定 **`7800`**）を設定しておくと、`tools/image_provider_novel_manga_batch.py` が step1-pages ジョブ組み立て時に **自動圧縮**（`trim_prompt_to_byte_limit`）を適用する。

圧縮は次の 4 フェーズを順番に試み、上限に収まった時点で停止する：

| フェーズ | 除去対象 | 節約効果の目安 |
|----------|----------|---------------|
| 1 | `render_instruction` ブロック行 | 中〜大（YAML IR 由来の作画依頼文） |
| 2 | `- tag:` 行（キャラ固定タグ列） | 大（繰り返しキャラ登場で特に効く） |
| 3 | `- 日本語訳:` 行 | 中（日本語訳付きタグ行） |
| 4 | バイト数ベースの末尾切り捨て + `[...省略]` | 最終手段 |

**設定確認コマンド**:

```bash
# config に max_prompt_bytes が設定されているか確認
python -c "import json; d=json.load(open('config/image_generation.json')); print(d['providers']['grok'].get('max_prompt_bytes', '未設定'))"
```

**圧縮結果の確認**（dry-run で実際のプロンプトバイト数を見る）:

```bash
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages --provider grok --dry-run
```

**注意**: `max_prompt_bytes` が未設定のまま step1-pages を Grok へ送ると **HTTP 400（プロンプト上限超過）** が返る。必ず `config/image_generation.json` の `providers.grok.max_prompt_bytes` を確認してから実行すること。

## 前提（OpenAI Images API）

- `.env` に **`OPENAI_API_KEY`** を記入する。
- 設定は **`config/image_generation.json`** の `providers.openai`。既定の通信先は `https://api.openai.com/v1/images/generations`。
- params JSON か CLI で **`provider=openai`** を選ぶ。
- 既定モデルは `config` の `providers.openai.default_model` で管理する。`gpt-image-2` のような次世代名を直接固定せず、`openai` provider の `model` を config で差し替える。
- YAMLをそのまま読ませる漫画ページ生成や、背景概念のような構造化プロンプトに向く。タグ列だけに強く寄せたい場合は NovelAI / Forge を優先する。

## 前提（OpenRouter）

- `.env` に **`OPENROUTER_API_KEY`** を記入する。
- 設定は **`config/image_generation.json`** の `providers.openrouter`。既定の通信先は `https://openrouter.ai/api/v1/chat/completions`。
- params JSON か CLI で **`provider=openrouter`** を選ぶ。
- OpenRouter の画像生成は `modalities: ["image", "text"]` と `image_config` を使う。画像は `choices[].message.images[].image_url.url` に base64 data URL として返る。
- 画像モデルは OpenRouter Models API の `output_modalities=image` で確認する。2026-05-06 時点では `nano_banana` → `google/gemini-2.5-flash-image`、`nano_banana_2` → `google/gemini-3.1-flash-image-preview`、`gpt_image_2` → `openai/gpt-5.4-image-2` を alias 登録している。Grok Imagine 相当は一覧で未確認。

## Codex / ChatGPT 内蔵画像生成の保管

ユーザーが「会話で画像を作って」「Codex内蔵の画像生成で試して」など、API provider ではなく **内蔵 `image_gen` ツール**を意図している場合は、`provider=openai` ではなく会話側の画像生成ツールを使う。

内蔵画像生成は API キーを必要とせず、生成画像は既定で `C:\Users\Owner\.codex\generated_images\...` に保存される。作品で使う画像は、この既定保存先のままにせず、作品フォルダへコピーして保管する。

推奨手順:

1. 内蔵 `image_gen` で画像を生成する。
2. 生成後、`C:\Users\Owner\.codex\generated_images\...` の画像ファイルを確認する。
3. `tools/codex_builtin_image_archive.py` で作品フォルダへコピーし、同名 JSON メタを残す。

例:

```bash
python tools/codex_builtin_image_archive.py \
  --source "C:/Users/Owner/.codex/generated_images/<id>/<file>.png" \
  --dest-dir "novels/<作品>/manga/_assets/manga_01/comic" \
  --prefix "manga_01_p01_k01_builtin_imagegen" \
  --note "Codex内蔵画像生成で試作した漫画コマ"
```

この運用は、`tools/image_provider_generate.py provider=openai` とは別物として扱う。`provider=openai` は OpenAI API 直叩き、内蔵 `image_gen` は ChatGPT/Codex 会話上の生成機能である。

## 保存先の約束（推奨）

`.rulesync/rules/overview.md` の **画像ストック** とスキル **`novel-image-layout`** に合わせるのが第一候補。

| 種別 | 推奨パス（`output_dir`） | メモ |
|------|-------------------------|------|
| 漫画コマ用 | `novels/<...>/manga/_assets/<manga_XX>/comic/` またはコマ別なら `.../comic/k03` など | 一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N` |
| キャラ立ち絵・表情 | `novels/<...>/tag/<romaji>/` | `tag/<romaji>.md` と**同名フォルダ**に画像を集約。作成は `novel_image_layout.py scaffold` |

従来の `outputs/` や `assets/characters/` への退避も可だが、**作品フォルダ内でタグ MD・漫画 MD と並べて追跡**するなら上表を優先する。

`output_dir` は **リポジトリルートからの相対パス可**（スクリプトが絶対パスに解決）。

## パラメータ JSON（公開スキーマ）

`tools/fixtures/forge_params.example.json`・`forge_params.flux.example.json`・`novelai_params.example.json`・`grok_params.example.json` を基準にする。

- **必須**: `provider`, `prompt`, `output_dir`
- **共通の任意**: `negative_prompt`, `seed`, `width`, `height`, `steps`, `cfg_scale`, `sampler_name`, `file_prefix`, `count`（1〜`max_count`）
- **Forge の任意**: `scheduler`, `distilled_cfg_scale`, `aspect_ratio_preset`
- **NovelAI の任意**: `model`, `action`, `uc_preset`, `quality_toggle`, `params_version`, `sm`, `sm_dyn`
- **Grok の任意**: `model`, `response_format`, `aspect_ratio`, `aspect_ratio_preset`, `resolution`
- **OpenAI の任意**: `model`, `size`, `quality`, `background`, `output_format`, `response_format`, `moderation`

Forge は **`save_images: false` / `send_images: true`**、NovelAI は zip または JSON 応答を Python 側で保存する。保存名:

`{output_dir}/{file_prefix}_{timestamp}_{seed}.png`
同名に生成メタ（リクエスト内容・`info` があれば）を **`.json`** で保存。

## 実行例

**ドライラン**（HTTP しない）:

```bash
python tools/image_provider_generate.py --params tools/fixtures/forge_params.example.json --dry-run
```

```bash
python tools/image_provider_generate.py --provider forge --json << EOF
{
  "provider": "forge",
  "prompt": "manga page, monochrome, speed lines",
  "output_dir": "outputs/forge",
  "file_prefix": "forge_manga",
  "aspect_ratio_preset": "manga_b5_portrait"
}
EOF
```

```bash
python tools/image_provider_generate.py --params tools/fixtures/novelai_params.example.json --dry-run
```

```bash
python tools/image_provider_generate.py --params tools/fixtures/grok_params.example.json --dry-run
```

**本番**（Forge 起動済み・保存先あり）:

```bash
python tools/image_provider_generate.py --params tools/fixtures/forge_params.example.json --json
```

```bash
python tools/image_provider_generate.py --provider novelai --params tools/fixtures/novelai_params.example.json --json
```

```bash
python tools/image_provider_generate.py --provider grok --params tools/fixtures/grok_params.example.json --json
```

```bash
python tools/image_provider_generate.py --provider grok --json << EOF
{
  "provider": "grok",
  "prompt": "manga page, black and white, dynamic action",
  "output_dir": "outputs/grok",
  "file_prefix": "manga_test",
  "aspect_ratio_preset": "manga_b5_portrait",
  "resolution": "2k"
}
EOF
```

`forge_params.example.json` をコピーして `prompt` / `output_dir` だけ書き換えた JSON を使ってもよい（`your_params.json` のような名前は自分で作成する）。

**標準入力**（パラメータ JSON）:

```bash
type params.json | python tools/image_provider_generate.py --json
```

## キャラタグ正本（YAML IR）の書式（ブレ防止）

一括生成 **`tools/image_provider_novel_tag_batch.py`** は、`tag/characters/*.yaml`（YAML IR）を直接読む。`tag/<romaji>.md` は参照しない。

- **正本**: `tag/characters/<character_id>.yaml`（スキル **`manga-prompt-ir`** の `schemas/character.py` / `examples/character.yaml`）
- **固定タグ**: `character_tags`・`costume.outfit_tags`・`manga_rules.consistency_tags`・`appearance.species_features`・`appearance.distinctive_features` を結合
- **バリアント**: `prompt_variants[].danbooru_tags`（`variant_id` ごと）
- **YAML 構造の検証**: スキル **`novel-tag-character-consistency`** および `python tools/novel_prompt_ir_validate.py novels/<作品フォルダ>`
- 実行前は必ず **`--dry-run`** でジョブ数・プロバイダ・プロンプト先頭を確認する。

## ワークフロー（タグ → 画像）

1. **Tag Mode** / **Manga Tag Mode** でタグ・キャプションをファイルに出力する（`_how_to/tag.md` と **`novel-tag-md-format`** に従い、可能なら上記のファイル形式に揃える）。
2. その英語タグ／caption を **`prompt` にコピー**（必要なら `negative_prompt` を作品用に固定）。
3. `params.json` を1枚ごと、または `count` で連続生成。
4. 生成結果の PNG を、該当 `manga_XX.md` または `tag/*.md` の節に**ファイル名で参照**するメモを追記すると追跡しやすい。

**一括（`tag/characters/*.yaml` の `prompt_variants` → 各 `tag/<char_id>/` へ1枚ずつ）** は `tools/image_provider_novel_tag_batch.py` を使う（スキル **`novel-image-layout`** のフォルダ規約と整合）。

```bash
# プロバイダは .env の MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT を使う（未設定なら config の default_provider）
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --dry-run
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider forge --aspect-ratio manga_b5_portrait
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider novelai
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider grok --aspect-ratio manga_b5_portrait --resolution 2k
# キャラ・バリアントを絞る（YAML IR の character_id / variant_id を指定）
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --only-char kazuki
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --only-char kazuki el --variant-id normal battle
python tools/image_provider_novel_tag_batch.py novels/051_神のダンジョンβテスター --variant-id normal
```

**一括（`manga/manga_*.md` の各 Page・## step1 内 `tag:`〜`和訳:` → `manga/_assets/<manga_XX>/comic/`）** は `tools/image_provider_novel_manga_batch.py` を使う。

- `--source step1-panels`（既定）: Step1 の `tag:` を**コマ単位**で抽出して生成する。背景資料と合成する場合は **`--omit-panel-background`**（`step1-panels` のみ）。
- `--source step1-pages`: 各 Page の **Step1 全体を1ジョブ**として扱い、**各コマの詳細情報を保ったままページ丸ごとの漫画画像**を出したいときに使う。**既定の正式対応先は Grok**。`--style-helper` 未指定時は、**精密ページ生成向けの画風補助文**を自動付与する。**Nanobanana は導入後に同系統へ加える想定**。
- `--source step2-pages`: 各 Page の **Step2 全体を1ジョブ**として扱い、**ページ丸ごとの漫画画像**を出したいときに使う。**既定の正式対応先は Grok**。`--style-helper` 未指定時は、**商業カラーマンガ寄りの画風補助文**を自動付与する。**Nanobanana は導入後に同系統へ加える想定**。

- **既定の保存先**は `manga/_assets/<manga_XX>/comic/` **直下**。背景資料は同章の `backgrounds/`。分類は**章（`manga_XX`）まで**で十分とし、`file_prefix` に `manga_01_p02_k03` のように **ページ番号・コマ番号**を含めて同一フォルダ内で区別する。
- **`--subdir-by-page`**（`.../manga_01/p01/`, `p02/` …）は **任意**。本リポジトリでは**推奨運用・ルールに含めない**（手順でページ単位フォルダ分けを既定にしない）。特別な理由があるときだけ使う。
- **`novel_image_layout.py scaffold --panels N` が作る `k01`〜`kNN`** は **「1ページ内のコマ用スロット」**の任意フォルダ。多ページの MD では **ページ番号 `p##` と混同しないこと**（本一括スクリプトの既定では **k## へは保存しない**）。

```bash
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --dry-run
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider forge --aspect-ratio manga_b5_portrait
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01
# （任意・本リポジトリでは非推奨）ページ単位サブフォルダがどうしても必要なときだけ:
# python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01 --subdir-by-page
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider novelai
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --aspect-ratio manga_b5_portrait --resolution 2k
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --source step1-pages --aspect-ratio manga_b5_portrait --resolution 2k
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --source step2-pages --aspect-ratio manga_b5_portrait --resolution 2k
python tools/image_provider_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider novelai --no-character-anchors
```

## エラー時

- `logs/image_provider_generate.log` に要約を追記。
- **HTTP 404**（`{"detail":"Not Found"}`）→ **REST API 未登録**。`--api` 付きで Forge を再起動し、`--probe` で `/sdapi/v1/samplers` が 200 になるか確認。
- **NovelAI が HTTP 403 で HTML（Cloudflare「Access denied」）** → 多くは **WAF がクライアントをブロック**している状態。`config/image_generation.json` の `providers.novelai.default_request_headers`（`User-Agent` / `Origin` / `Referer`）が `tools/image_provider_generate.py` で自動付与される。それでも出る場合は **VPN の出口・データセンター IP** を変える、**住宅系プロキシ**（`HTTPS_PROXY` 環境変数は urllib が参照）を試す、公式サイトが同じ回線で開けるか確認する。
- **NovelAI が HTTP 500（`Internal Server Error` のみ）** → `nai-diffusion-4*` 系は API が **`v4_prompt` / `v4_negative_prompt`** を要求する一方、**`ucPreset` に v1 用の 0〜2 を渡すとサーバ側で不正**になりうる。`tools/image_provider_generate.py` は v4 系で **0〜2 を Heavy(4) に寄せ**、上記フィールドと `noise_schedule` 等を付与する。それでも失敗する場合は **モデル名・`steps` / 解像度**を UI の推奨に合わせる。
- **Grok が HTTP 400（プロンプト上限超過）** → xAI API はプロンプトを **UTF-8 バイト数**で制限する（日本語 1 文字 ≒ 3 バイト）。`config/image_generation.json` の `providers.grok.max_prompt_bytes`（既定 `7800`）が設定されていれば `tools/image_provider_novel_manga_batch.py` が自動圧縮する。設定が **未設定**の場合は `7800` を追加してから再実行する（詳細は「Grok プロンプト上限と自動圧縮」節）。
- **Grok の URL 応答が期限切れ** → xAI docs でも生成 URL は一時的。`response_format: "b64_json"` を優先し、即保存する。
- HTTP その他 4xx/5xx → レスポンス先頭を stderr に表示。
- **返却 PNG が異常に小さい**（既定 512 バイト未満）→ **exit 8**。Forge は `image_generation.json` の Flux 向け数値・VAE・モデルを UI と揃えて再試行。NovelAI は prompt / sampler / model の組み合わせを見直す。

## 関連パス

- スクリプト: `tools/image_provider_generate.py`
- タグ一括: `tools/image_provider_novel_tag_batch.py`（`tag/characters/*.yaml` の `prompt_variants` を YAML 直読みして連続 txt2img）
- 漫画一括: `tools/image_provider_novel_manga_batch.py`（`manga/manga_*.md` の step1 内 `tag:` ブロックをコマ順に txt2img）
- 設定: `config/image_generation.json`, `.env`
- 例: `tools/fixtures/forge_params.example.json`, `tools/fixtures/novelai_params.example.json`, `tools/fixtures/grok_params.example.json`
- タグルール: `_how_to/tag.md`, `_how_to/manga_tag.md`, `_how_to/manga.md`
