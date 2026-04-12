# Monogatari Coach

Monogatari Coach は、小説執筆の企画、設計、執筆、推敲、評価、画像生成、漫画展開までを一貫して支援するリポジトリです。ルートの `README.md` は最短の入口に絞り、詳しい説明は `docs/` 配下へ整理しています。

## Docs

- [Docs Index](docs/index.md)
- [Getting Started](docs/getting-started/index.md)
- [Image Generation](docs/image-generation/index.md)
- [Workflow](docs/workflow/index.md)
- [Project Structure](docs/project-structure/index.md)
- [Operations](docs/operations/index.md)
- [Community](docs/community/index.md)

## Quick Start

1. `rulesync` を導入

```bash
npm install -g rulesync
```

2. `uv` を導入して初回セットアップ

```bash
uv run python howto_init.py
```

3. `.env` を整える

```dotenv
NOVELAI_ACCESS_TOKEN=
XAI_API_KEY=
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=forge
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=flux
MONOCRI_GROK_MODEL_TIER_DEFAULT=standard
```

## 主要パス

- ルールの正本:
  [`.rulesync/rules/overview.md`](.rulesync/rules/overview.md)
- スキルの正本:
  [`.rulesync/skills/`](.rulesync/skills/)
- 創作技法テンプレートの正本:
  [`_how_to.example/`](_how_to.example/)
- ローカル試行:
  [`tools_temp/README.md`](tools_temp/README.md)

## 日常運用でよく使うコマンド

初回化:

```bash
uv run python howto_init.py
```

ルール再生成:

```bash
rulesync generate
```

文字数確認:

```bash
uv run python tools/novel_char_count.py novels/NNN_作品タイトル
```

Grok dry-run:

```bash
python tools/forge_generate.py --provider grok --params tools/fixtures/grok_params.tier_test.example.json --dry-run
```

## ライセンス

MIT License
