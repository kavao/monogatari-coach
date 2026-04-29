# Image Generation

Forge / NovelAI / Grok / OpenAI の画像生成運用をまとめたページです。

## 関連ファイル

- 実行クライアント: [`/tools/forge_generate.py`](../../tools/forge_generate.py)
- 漫画ページ一括生成: [`/tools/forge_novel_manga_batch.py`](../../tools/forge_novel_manga_batch.py)
- キャラタグ一括生成: [`/tools/forge_novel_tag_batch.py`](../../tools/forge_novel_tag_batch.py)
- 設定: [`/config/image_generation.json`](../../config/image_generation.json)
- 環境変数テンプレート: [`/.env.example`](../../.env.example)
- 詳細スキル: [`/.rulesync/skills/forge-txt2img/SKILL.md`](../../.rulesync/skills/forge-txt2img/SKILL.md)

---

## provider の一覧と使い分け

`config/image_generation.json` の `providers` に登録されている provider は次のとおりです。

| provider | モデル | 主な用途 |
|----------|--------|---------|
| `forge` | UI で読み込んだ Checkpoint（SDXL / Flux） | ローカルコマ生成 |
| `novelai` | `nai-diffusion-4-5-full` など | コマ生成（クラウド） |
| `grok` | `grok-imagine-image`（standard） | キャラタグ一括・単体画像 |
| `grok_pro` | `grok-imagine-image-pro` | 漫画ページ生成（step1-pages / step2-pages / background-concepts） |
| `openai` | `gpt-image-1.5` など | ページ生成の代替 |

`grok` と `grok_pro` は同じ xAI API エンドポイントを使いますが、`config/image_generation.json` の `default_model` が異なります。ツール内部では `_GROK_FAMILY = {"grok", "grok_pro"}` として同系として扱います。

---

## .env の provider 既定値

`--provider` を省略したとき、バッチツールは `.env` の下記変数を参照します。

```dotenv
# キャラクタータグ一括生成 (forge_novel_tag_batch.py)
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai

# 漫画コマ生成 (--source step1-panels)
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=novelai

# 漫画精密ページ生成 (--source step1-pages)  ← 既定: grok_pro
MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro

# 漫画ページ生成 (--source step2-pages)  ← 既定: grok_pro
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok_pro

# 漫画背景概念生成 (--source background-concepts)
MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT=grok

# Forge のモデル族 (sdxl / flux)
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=
```

優先順位: CLI `--provider` > `.env` 用途別変数 > `config/image_generation.json` の `default_provider`

---

## 漫画生成の運用

### 生成モードとプロバイダの対応

| モード | オプション | 既定 provider | 説明 |
|--------|-----------|--------------|------|
| コマ生成 | `--source step1-panels` | `novelai` | 各コマを別画像として出力 |
| 精密ページ生成 | `--source step1-pages` | `grok_pro` | Step1 の詳細情報を保ったまま 1 ページ 1 枚で出力 |
| ページ生成 | `--source step2-pages` | `grok_pro` | Step2 のレイアウト要約から 1 ページ 1 枚で出力 |
| 背景概念生成 | `--source background-concepts` | `grok` | 人物なしの背景・空間設計を先出し |

Forge / NovelAI はコマ生成向け。step1-pages / step2-pages の正式対応先は `grok_pro` / `openai`。

### Grok のプロンプト上限と自動圧縮

Grok API のプロンプト上限は **UTF-8 バイト数**で管理されています（日本語 1 文字 ≒ 3 バイト）。

`config/image_generation.json` の `providers.grok_pro.max_prompt_bytes`（既定 `7800`）が設定されていると、`forge_novel_manga_batch.py` が step1-pages のプロンプトを自動圧縮します。

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
python tools/forge_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --dry-run

# dry-run 例（キャラタグ一括）
python tools/forge_novel_tag_batch.py novels/<作品> --dry-run
```

dry-run の出力で `provider: grok_pro` / `jobs: 4` などを確認し、ユーザーの「OK」「進めて」などの承認後に `--dry-run` を外して本番実行します。

---

## よく使うコマンド

### キャラタグ一括生成

```bash
# dry-run（provider 確認）
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター --dry-run

# 本番
python tools/forge_novel_tag_batch.py novels/051_神のダンジョンβテスター
```

### 漫画コマ生成（step1-panels / novelai）

```bash
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-panels --dry-run

python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-panels
```

### 漫画精密ページ生成（step1-pages / grok_pro）

```bash
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k --dry-run

python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step1-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k
```

### 漫画ページ生成（step2-pages / grok_pro）

```bash
python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k --dry-run

python tools/forge_novel_manga_batch.py novels/051_神のダンジョンβテスター \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --resolution 2k
```

### provider を明示して上書き

```bash
# grok_pro を明示
python tools/forge_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider grok_pro

# openai を使う
python tools/forge_novel_manga_batch.py novels/<作品> \
  --manga-stem manga_01 --source step1-pages --provider openai
```

### Forge の疎通確認

```bash
python tools/forge_generate.py --probe --provider forge
```

---

## 画像の保存先

| 種別 | 保存先 |
|------|--------|
| 漫画ページ / コマ | `novels/<作品>/manga/_assets/<manga_XX>/` |
| キャラクター立ち絵 | `novels/<作品>/tag/<romaji>/` |

フォルダ一括作成は `python tools/novel_image_layout.py scaffold <作品> --panels N`。

---

## 参考

- プロバイダ詳細・Flux 固有パラメータ: [`.rulesync/skills/forge-txt2img/SKILL.md`](../../.rulesync/skills/forge-txt2img/SKILL.md)
- ワークフロー全体: [`.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md)
