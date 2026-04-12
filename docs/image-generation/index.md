# Image Generation

Forge / NovelAI / Grok の画像生成運用をまとめたページです。

## 関連ファイル

- 実行クライアント:
  [`/tools/forge_generate.py`](../../tools/forge_generate.py)
- バッチ生成:
  [`/tools/forge_novel_tag_batch.py`](../../tools/forge_novel_tag_batch.py)
  [`/tools/forge_novel_manga_batch.py`](../../tools/forge_novel_manga_batch.py)
- 設定:
  [`/config/image_generation.json`](../../config/image_generation.json)
- 環境変数テンプレート:
  [`/.env.example`](../../.env.example)
- 詳細スキル:
  [`/.rulesync/skills/forge-txt2img/SKILL.md`](../../.rulesync/skills/forge-txt2img/SKILL.md)

## provider の既定値

`--provider` を明示しないときは `.env` の既定値が使われます。

```dotenv
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=forge
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok
```

- `MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT`
  キャラクタータグ画像の既定 provider
- `MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT`
  `step1-panels` と `step1-pages` の既定 provider
- `MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT`
  `step2-pages` の既定 provider

優先順位:

- CLI の `--provider`
- `.env` の用途別既定値
- `config/image_generation.json` の `default_provider`

## Forge の既定モデル族

```dotenv
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=flux
```

- `sdxl` または `flux`
- `flux` を選ぶと `config/image_generation.json` の `providers.forge.presets.flux` と `aspect_ratio_presets.flux` 側が使われます

## Grok の standard / pro

```dotenv
MONOCRI_GROK_MODEL_TIER_DEFAULT=standard
```

- `standard` は `grok-imagine-image`
- `pro` は `grok-imagine-image-pro`
- 実モデル名の対応は `config/image_generation.json` の `providers.grok.model_aliases` で管理します

## よく使うコマンド

NovelAI:

```bash
python tools/forge_generate.py --provider novelai --params tools/fixtures/novelai_params.example.json --json
```

Grok:

```bash
python tools/forge_generate.py --provider grok --params tools/fixtures/grok_params.example.json --json
```

Forge:

```bash
python tools/forge_generate.py --provider forge --params tools/fixtures/forge_params.example.json --json
```

## Grok standard / pro の比較

比較用 fixture:

- [`/tools/fixtures/grok_params.tier_test.example.json`](../../tools/fixtures/grok_params.tier_test.example.json)

PowerShell での dry-run:

```powershell
$env:MONOCRI_GROK_MODEL_TIER_DEFAULT='standard'
python tools/forge_generate.py --provider grok --params tools/fixtures/grok_params.tier_test.example.json --dry-run
```

```powershell
$env:MONOCRI_GROK_MODEL_TIER_DEFAULT='pro'
python tools/forge_generate.py --provider grok --params tools/fixtures/grok_params.tier_test.example.json --dry-run
```

## 漫画生成の運用

- `step1-panels`
  コマ単位生成。Forge / NovelAI / Grok で利用可能
- `step1-pages`
  Step1 全体をページ単位で精密生成。Grok 正式対応
- `step2-pages`
  Step2 をページ単位で生成。Grok 正式対応

詳細は [`/.rulesync/skills/forge-txt2img/SKILL.md`](../../.rulesync/skills/forge-txt2img/SKILL.md) と [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) を参照してください。
