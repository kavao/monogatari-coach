---
name: forge-txt2img
description: >-
  Stable Diffusion Forge / NovelAI / Grok(xAI) の REST API へ
  tools/forge_generate.py で txt2img。タグ生成後に画像を outputs または
  作品フォルダへ保存する。
targets: ["*"]
---

## 目的

`_how_to/manga_tag.md` / `manga.md` で **漫画タグ**、`_how_to/tag.md` で **キャラクタータグ**を用意した**あと**、同じプロンプト思想で **Forge / NovelAI / Grok** で画像を生成し、リポジトリ内の決めたフォルダにストックする。

v2 は **txt2img のみ**・`provider` で **`forge` / `novelai` / `grok`** を切り替える。既定は `config/image_generation.json` の **`default_provider`**。Forge は UI で読み込んだモデルに追従し、NovelAI は `.env` の **`NOVELAI_ACCESS_TOKEN`**、Grok は **`XAI_API_KEY`** を使って REST API に接続する。

## 漫画生成の用語整理

- **コマ生成**:
  `manga_XX.md` の **Step1** を使い、**各コマを別画像**として出す運用。`tools/forge_novel_manga_batch.py` の **`--source step1-panels`**。
- **精密ページ生成**:
  `manga_XX.md` の **Step1 全体**を使い、**各コマの詳細指示を保持したまま 1ページ全体を1枚で出す**運用。`tools/forge_novel_manga_batch.py` の **`--source step1-pages`**。
- **ページ生成**:
  `manga_XX.md` の **Step2** を使い、**1ページ全体を1枚**として出す運用。`tools/forge_novel_manga_batch.py` の **`--source step2-pages`**。
- **既定**:
  会話で明示がない場合は **コマ生成** とみなす。

## 推奨プロバイダ分担（Step1 コマ／ページ系）

本リポジトリの**既定の運用イメージ**は次のとおり。

| モード | `forge_novel_manga_batch.py` | 推奨プロバイダ | `tag/*.md` 自動注入 |
|--------|------------------------------|----------------|---------------------|
| **コマ生成（Step1）** | `--source step1-panels`（既定） | **Forge（ローカル）** または **NovelAI** | **オン（既定）でよい**。NovelAI 向けに **`--no-character-anchors` は原則不要**（コマ単体で `tag:`＋注入で固定特徴を揃える想定）。 |
| **精密ページ生成** | `--source step1-pages` | **Grok**（正式対応） | 注入オンを既定とするが、**拒否が出る場合**は `_how_to/manga.md` の Step2 的な言い換えに寄せる／**`--no-character-anchors`** を検討。 |
| **ページ生成** | `--source step2-pages` | **Grok**（正式対応） | 同上。Step2 本文はもともと**モデレーションに触れにくい抽象レイアウト**を想定。 |

**Grok が「必要になる」流れ**: 1ページを1枚にまとめる **step1-pages / step2-pages** は、**Forge／NovelAI をページ生成の正式先に含めない**既定のため、**クラウドでページ丸ごとを出すときは Grok** を使う。コマ単体の Step1 は **Forge か NovelAI** で足りる、という分担。

## 漫画生成の API 対応範囲（2026-04-12 時点）

- **コマ生成**:
  **Forge / NovelAI / Grok** に対応。
- **精密ページ生成**:
  **Grok** を正式対応とする。**Nanobanana は導入予定の想定対応先**。
- **ページ生成**:
  **Grok** を正式対応とする。**Nanobanana は導入予定の想定対応先**。
- **固定特徴・状況タグの自動注入**:
  **`step1-panels` / `step1-pages` / `step2-pages`** では、作品フォルダの **`tag/*.md`** を参照し、本文に登場が見えるキャラごとに **状況に最も近い Danbooru Tags ブロック**を prompt へ自動注入する。本文側には **キャラ名** と、必要なら **オンボーディング / βテスト開始 / 緊急修復** などの状況語を明記しておくと安定しやすい。
- **注入のオフ（`--no-character-anchors`）**:
  **`tag/*.md` を読まず**、STYLE_PREFIX ＋ Step 本文のみを送る。使いどころの例: **Grok で step1-pages / step2-pages が拒否**するとき、または注入語を入れたくない実験時。**step1-panels を NovelAI で回す通常運用ではオフ不要**（上表「推奨プロバイダ分担」参照）。
- **ページ生成の非対応**:
  **Forge / NovelAI** は、このスキルの既定運用では **step1-pages / step2-pages の正式対応先に含めない**。

## 前提（Forge）

- Forge / WebUI を **`--api` 付き**で起動する（これが無いと `/sdapi/v1/txt2img` が **HTTP 404** になり、Gradio の「Running on http://127.0.0.1:7860」だけでは足りないことがある）。
  - 例: `webui-user.bat` で `set COMMANDLINE_ARGS=--api` のあと起動。
- 疎通確認: `python tools/forge_generate.py --probe`（`/docs` と `/sdapi/v1/samplers` の結果を表示。**samplers が 404 なら --api なし**の可能性が高い）。
- 設定はリポジトリルートの **`config/image_generation.json`**（必須）。Forge / NovelAI / Grok の各 `providers.*` と **`default_provider`** をここで管理する。`tools/forge_generate.py` の **`--config`** で別ファイルを指すことはできるが、**リポジトリ運用上の正本はこのファイル**とする。
- **画像生成前**に UI の Checkpoint が FLUX / SDXL のどちらかと `active_model_family` を揃える（詳細は `.rulesync/rules/overview.md` の「Forge 画像生成（txt2img）の事前確認」）。

### Forge + Flux（ブラウザと API を揃える）

- **Checkpoint / VAE / テキストエンコーダは API ペイロードに含めない**。起動中の Forge に UI で読み込んだものがそのまま使われる（**ブラウザの設定と一致させる**）。
- **リポジトリ既定の `active_model_family` は `sdxl`**（`presets.sdxl`: CFG 約 7・Euler a・1024² など）。**Flux** で回すときは **`active_model_family` を `flux`** にし、`presets.flux`（CFG 約 1・Euler・Schedule Simple・Distilled CFG など）を使う。
- Forge は API 自体は `width` / `height` 指定だが、このリポジトリでは **`aspect_ratio_preset`** を受け付け、`providers.forge.aspect_ratio_presets` から **family ごとの寸法**へ展開する。`square`、`portrait`、`manga_b5_portrait`、`story_vertical`、`landscape`、`wide` を用意している。
- **Flux の Checkpoint なのに SDXL 向けの CFG（例: 7）のまま** txt2img を叩くと、画が壊れる・返却 PNG が極小になることがある。逆に **SDXL で CFG 1** だけではプロンプト追従が弱くなりやすい。
- API 拡張フィールド: **`scheduler`**（例: `Simple`）・**`distilled_cfg_scale`**（例: `3.5`）。`tools/forge_generate.py` が `image_generation.json` または params JSON から付与する。
- 例: `tools/fixtures/forge_params.flux.example.json`
- **VAE 未設定・誤った VAE** でも UI では見えて API でだけ失敗する、というケースは起こりうる。生成ログの `info` や Forge のコンソールも参照する。

## 前提（NovelAI）

- `.env.example` を `.env` にコピーし、**`NOVELAI_ACCESS_TOKEN`** を記入する。初回セットアップでは `howto_init.py` / `init.bat` が未作成時に自動コピーする。
- 設定は **`config/image_generation.json`** の `providers.novelai`。既定の通信先は `https://image.novelai.net/ai/generate-image`。
- params JSON か CLI で **`provider=novelai`** を選ぶ。
- 画像設定（steps / guidance / sampler など）の意味は NovelAI 公式ドキュメントの Image Generation 節に揃える。REST の詳細は公開仕様が薄いため、エンドポイントや追加フィールドが変わった場合は **config 側で吸収**する前提で運用する。

## 前提（Grok / xAI）

- `.env` に **`XAI_API_KEY`** を記入する。
- 設定は **`config/image_generation.json`** の `providers.grok`。既定の通信先は `https://api.x.ai/v1/images/generations`。
- params JSON か CLI で **`provider=grok`** を選ぶ。
- 画像モデルは **`grok-imagine-image`**。`aspect_ratio`、`resolution`、`n`、`response_format` が公式に案内されている。
- このリポジトリでは `providers.grok.aspect_ratio_presets` により、`square`、`manga_b5_portrait`、`story_vertical` などの preset 名でも切り替えられる。**B5 実寸そのものは xAI の公式 ratio ではない**ため、`manga_b5_portrait` は **`3:4`** の近似 preset。
- 既定実装は **`response_format: "b64_json"`** で受け、URL の失効前にそのまま保存する。

## 保存先の約束（推奨）

`.rulesync/rules/overview.md` の **画像ストック** とスキル **`novel-image-layout`** に合わせるのが第一候補。

| 種別 | 推奨パス（`output_dir`） | メモ |
|------|-------------------------|------|
| 漫画コマ用 | `novels/<...>/manga/_assets/<manga_XX>/` またはコマ別なら `.../manga/_assets/<manga_XX>/k03` など | 一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N` |
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

Forge は **`save_images: false` / `send_images: true`**、NovelAI は zip または JSON 応答を Python 側で保存する。保存名:

`{output_dir}/{file_prefix}_{timestamp}_{seed}.png`  
同名に生成メタ（リクエスト内容・`info` があれば）を **`.json`** で保存。

## 実行例

**ドライラン**（HTTP しない）:

```bash
python tools/forge_generate.py --params tools/fixtures/forge_params.example.json --dry-run
```

```bash
python tools/forge_generate.py --provider forge --json << EOF
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
python tools/forge_generate.py --params tools/fixtures/novelai_params.example.json --dry-run
```

```bash
python tools/forge_generate.py --params tools/fixtures/grok_params.example.json --dry-run
```

**本番**（Forge 起動済み・保存先あり）:

```bash
python tools/forge_generate.py --params tools/fixtures/forge_params.example.json --json
```

```bash
python tools/forge_generate.py --provider novelai --params tools/fixtures/novelai_params.example.json --json
```

```bash
python tools/forge_generate.py --provider grok --params tools/fixtures/grok_params.example.json --json
```

```bash
python tools/forge_generate.py --provider grok --json << EOF
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
type params.json | python tools/forge_generate.py --json
```

## キャラ `tag/*.md` の書式（ブレ防止）

一括生成 **`tools/forge_novel_tag_batch.py`** は、`tag/*.md` 内の **番号付き見出し**と **`Danbooru Tags:` 直後の1行**を機械抽出する。**見出しレベル・インデント・タグを何行に折るか**がブレるとジョブが空になる。

- **正本**: `_how_to/tag.md` の **「Markdown ファイル形式（`tag/<romaji>.md`・機械抽出と整合）」**
- **短いチェックリスト**: スキル **`novel-tag-md-format`**（`.rulesync/skills/novel-tag-md-format/SKILL.md`）
- 執筆後は必ず **`--dry-run`** でジョブ数を確認する。

## ワークフロー（タグ → 画像）

1. **Tag Mode** / **Manga Tag Mode** でタグ・キャプションをファイルに出力する（`_how_to/tag.md` と **`novel-tag-md-format`** に従い、可能なら上記のファイル形式に揃える）。
2. その英語タグ／caption を **`prompt` にコピー**（必要なら `negative_prompt` を作品用に固定）。
3. `params.json` を1枚ごと、または `count` で連続生成。
4. 生成結果の PNG を、該当 `manga_XX.md` または `tag/*.md` の節に**ファイル名で参照**するメモを追記すると追跡しやすい。

**一括（`tag/*.md` の Danbooru 行 → 各 `tag/<romaji>/` へ1枚ずつ）** は `tools/forge_novel_tag_batch.py` を使う（スキル **`novel-image-layout`** のフォルダ規約と整合）。

```bash
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --dry-run
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider forge --aspect-ratio manga_b5_portrait
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider novelai
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider grok
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --provider grok --aspect-ratio manga_b5_portrait --resolution 2k
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --max-section 4
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --only-stem yuma --min-section 5 --max-section 7
```

**一括（`manga/manga_*.md` の各 Page・## step1 内 `tag:`〜`和訳:` → `manga/_assets/<manga_XX>/`）** は `tools/forge_novel_manga_batch.py` を使う。

- `--source step1-panels`（既定）: Step1 の `tag:` を**コマ単位**で抽出して生成する。
- `--source step1-pages`: 各 Page の **Step1 全体を1ジョブ**として扱い、**各コマの詳細情報を保ったままページ丸ごとの漫画画像**を出したいときに使う。**既定の正式対応先は Grok**。`--style-helper` 未指定時は、**精密ページ生成向けの画風補助文**を自動付与する。**Nanobanana は導入後に同系統へ加える想定**。
- `--source step2-pages`: 各 Page の **Step2 全体を1ジョブ**として扱い、**ページ丸ごとの漫画画像**を出したいときに使う。**既定の正式対応先は Grok**。`--style-helper` 未指定時は、**商業カラーマンガ寄りの画風補助文**を自動付与する。**Nanobanana は導入後に同系統へ加える想定**。

- **既定の保存先**は `manga/_assets/<manga_XX>/` **直下**（`file_prefix` に `manga_01_p02_k03` のように **ページ番号・コマ番号**が入り、overview の例どおり **同一フォルダで区別**する）。
- **ページごとにフォルダ分け**したいときは **`--subdir-by-page`**（例: `.../manga_01/p01/`, `p02/`, …）。
- **`novel_image_layout.py scaffold --panels N` が作る `k01`〜`kNN`** は **「1ページ内のコマ用スロット」**の任意フォルダ。多ページの MD では **ページ番号 `p##` と混同しないこと**（本一括スクリプトの既定では **k## へは保存しない**）。

```bash
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --dry-run
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider forge --aspect-ratio manga_b5_portrait
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01 --subdir-by-page
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider novelai
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --aspect-ratio manga_b5_portrait --resolution 2k
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --source step1-pages --aspect-ratio manga_b5_portrait --resolution 2k
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider grok --source step2-pages --aspect-ratio manga_b5_portrait --resolution 2k
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --provider novelai --no-character-anchors
```

## エラー時

- `logs/forge_generate.log` に要約を追記。
- **HTTP 404**（`{"detail":"Not Found"}`）→ **REST API 未登録**。`--api` 付きで Forge を再起動し、`--probe` で `/sdapi/v1/samplers` が 200 になるか確認。
- **NovelAI が HTTP 403 で HTML（Cloudflare「Access denied」）** → 多くは **WAF がクライアントをブロック**している状態。`config/image_generation.json` の `providers.novelai.default_request_headers`（`User-Agent` / `Origin` / `Referer`）が `tools/forge_generate.py` で自動付与される。それでも出る場合は **VPN の出口・データセンター IP** を変える、**住宅系プロキシ**（`HTTPS_PROXY` 環境変数は urllib が参照）を試す、公式サイトが同じ回線で開けるか確認する。
- **NovelAI が HTTP 500（`Internal Server Error` のみ）** → `nai-diffusion-4*` 系は API が **`v4_prompt` / `v4_negative_prompt`** を要求する一方、**`ucPreset` に v1 用の 0〜2 を渡すとサーバ側で不正**になりうる。`tools/forge_generate.py` は v4 系で **0〜2 を Heavy(4) に寄せ**、上記フィールドと `noise_schedule` 等を付与する。それでも失敗する場合は **モデル名・`steps` / 解像度**を UI の推奨に合わせる。
- **Grok の URL 応答が期限切れ** → xAI docs でも生成 URL は一時的。`response_format: "b64_json"` を優先し、即保存する。
- HTTP その他 4xx/5xx → レスポンス先頭を stderr に表示。
- **返却 PNG が異常に小さい**（既定 512 バイト未満）→ **exit 8**。Forge は `image_generation.json` の Flux 向け数値・VAE・モデルを UI と揃えて再試行。NovelAI は prompt / sampler / model の組み合わせを見直す。

## 関連パス

- スクリプト: `tools/forge_generate.py`
- タグ一括: `tools/forge_novel_tag_batch.py`（`tag/*.md` の Danbooru Tags を抽出して連続 txt2img）
- 漫画一括: `tools/forge_novel_manga_batch.py`（`manga/manga_*.md` の step1 内 `tag:` ブロックをコマ順に txt2img）
- 設定: `config/image_generation.json`, `.env`
- 例: `tools/fixtures/forge_params.example.json`, `tools/fixtures/novelai_params.example.json`, `tools/fixtures/grok_params.example.json`
- タグルール: `_how_to/tag.md`, `_how_to/manga_tag.md`, `_how_to/manga.md`
