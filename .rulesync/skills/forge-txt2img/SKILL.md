---
name: forge-txt2img
description: >-
  Stable Diffusion Forge（A1111 互換 API）へ tools/forge_generate.py で txt2img。
  タグ生成後に画像を outputs または作品フォルダへ保存する。
targets: ["*"]
---

## 目的

`_how_to/manga_tag.md` / `manga.md` で **漫画タグ**、`_how_to/tag.md` で **キャラクタータグ**を用意した**あと**、同じプロンプト思想で **Forge で画像を生成**し、リポジトリ内の決めたフォルダにストックする。

v1 は **txt2img のみ**・**既定は Forge 側で読み込んだモデルに追従**（`config/forge_config.json` の **`active_model_family`** で **`presets.sdxl`** / **`presets.flux`** を切り替え。**標準は SDXL**）・**モデル切替・拡張は API から行わない**（Forge UI で Checkpoint / VAE を選ぶ前提）。

## 前提（Forge）

- Forge / WebUI を **`--api` 付き**で起動する（これが無いと `/sdapi/v1/txt2img` が **HTTP 404** になり、Gradio の「Running on http://127.0.0.1:7860」だけでは足りないことがある）。
  - 例: `webui-user.bat` で `set COMMANDLINE_ARGS=--api` のあと起動。
- 疎通確認: `python tools/forge_generate.py --probe`（`/docs` と `/sdapi/v1/samplers` の結果を表示。**samplers が 404 なら --api なし**の可能性が高い）。
- 設定はリポジトリルートの **`config/forge_config.json`**（`base_url`・`active_model_family`・`presets`・タイムアウト・許可 sampler など）。**画像生成前**に UI の Checkpoint が FLUX / SDXL のどちらかと `active_model_family` を揃える（詳細は `.rulesync/rules/overview.md` の「Forge 画像生成（txt2img）の事前確認」）。

### Forge + Flux（ブラウザと API を揃える）

- **Checkpoint / VAE / テキストエンコーダは API ペイロードに含めない**。起動中の Forge に UI で読み込んだものがそのまま使われる（**ブラウザの設定と一致させる**）。
- **リポジトリ既定の `active_model_family` は `sdxl`**（`presets.sdxl`: CFG 約 7・Euler a・1024² など）。**Flux** で回すときは **`active_model_family` を `flux`** にし、`presets.flux`（CFG 約 1・Euler・Schedule Simple・Distilled CFG など）を使う。
- **Flux の Checkpoint なのに SDXL 向けの CFG（例: 7）のまま** txt2img を叩くと、画が壊れる・返却 PNG が極小になることがある。逆に **SDXL で CFG 1** だけではプロンプト追従が弱くなりやすい。
- API 拡張フィールド: **`scheduler`**（例: `Simple`）・**`distilled_cfg_scale`**（例: `3.5`）。`tools/forge_generate.py` が `forge_config.json` または params JSON から付与する。
- 例: `tools/fixtures/forge_params.flux.example.json`
- **VAE 未設定・誤った VAE** でも UI では見えて API でだけ失敗する、というケースは起こりうる。生成ログの `info` や Forge のコンソールも参照する。

## 保存先の約束（推奨）

`.rulesync/rules/overview.md` の **画像ストック** とスキル **`novel-image-layout`** に合わせるのが第一候補。

| 種別 | 推奨パス（`output_dir`） | メモ |
|------|-------------------------|------|
| 漫画コマ用 | `novels/<...>/manga/_assets/<manga_XX>/` またはコマ別なら `.../manga/_assets/<manga_XX>/k03` など | 一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N` |
| キャラ立ち絵・表情 | `novels/<...>/tag/<romaji>/` | `tag/<romaji>.md` と**同名フォルダ**に画像を集約。作成は `novel_image_layout.py scaffold` |

従来の `outputs/` や `assets/characters/` への退避も可だが、**作品フォルダ内でタグ MD・漫画 MD と並べて追跡**するなら上表を優先する。

`output_dir` は **リポジトリルートからの相対パス可**（スクリプトが絶対パスに解決）。

## パラメータ JSON（公開スキーマ）

`tools/fixtures/forge_params.example.json` と同型（Flux 用の別例: `forge_params.flux.example.json`）。

- **必須**: `prompt`, `output_dir`（他は `forge_config.json` 既定で補完可）
- **任意**: `negative_prompt`, `seed`, `width`, `height`, `steps`, `cfg_scale`, `sampler_name`, `scheduler`, `distilled_cfg_scale`, `file_prefix`, `count`（1〜`max_count`）

内部で Forge へ送る payload は **`save_images: false` / `send_images: true`**（返却 base64 を Python 側で保存）。保存名:

`{output_dir}/{file_prefix}_{timestamp}_{seed}.png`  
同名に生成メタ（リクエスト内容・`info` があれば）を **`.json`** で保存。

## 実行例

**ドライラン**（HTTP しない）:

```bash
python tools/forge_generate.py --params tools/fixtures/forge_params.example.json --dry-run
```

**本番**（Forge 起動済み・保存先あり）:

```bash
python tools/forge_generate.py --params tools/fixtures/forge_params.example.json --json
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
```

**一括（`manga/manga_*.md` の各 Page・## step1 内 `tag:`〜`和訳:` → `manga/_assets/<manga_XX>/`）** は `tools/forge_novel_manga_batch.py` を使う。

- **既定の保存先**は `manga/_assets/<manga_XX>/` **直下**（`file_prefix` に `manga_01_p02_k03` のように **ページ番号・コマ番号**が入り、overview の例どおり **同一フォルダで区別**する）。
- **ページごとにフォルダ分け**したいときは **`--subdir-by-page`**（例: `.../manga_01/p01/`, `p02/`, …）。
- **`novel_image_layout.py scaffold --panels N` が作る `k01`〜`kNN`** は **「1ページ内のコマ用スロット」**の任意フォルダ。多ページの MD では **ページ番号 `p##` と混同しないこと**（本一括スクリプトの既定では **k## へは保存しない**）。

```bash
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --dry-run
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター --manga-stem manga_01 --subdir-by-page
```

## エラー時

- `logs/forge_generate.log` に要約を追記。
- **HTTP 404**（`{"detail":"Not Found"}`）→ **REST API 未登録**。`--api` 付きで Forge を再起動し、`--probe` で `/sdapi/v1/samplers` が 200 になるか確認。
- HTTP その他 4xx/5xx → レスポンス先頭を stderr に表示。
- **返却 PNG が異常に小さい**（既定 512 バイト未満）→ **exit 8**。`forge_config.json` の Flux 向け数値・VAE・モデルを UI と揃えて再試行。

## 関連パス

- スクリプト: `tools/forge_generate.py`
- タグ一括: `tools/forge_novel_tag_batch.py`（`tag/*.md` の Danbooru Tags を抽出して連続 txt2img）
- 漫画一括: `tools/forge_novel_manga_batch.py`（`manga/manga_*.md` の step1 内 `tag:` ブロックをコマ順に txt2img）
- 設定: `config/forge_config.json`
- 例: `tools/fixtures/forge_params.example.json`
- タグルール: `_how_to/tag.md`, `_how_to/manga_tag.md`, `_how_to/manga.md`
