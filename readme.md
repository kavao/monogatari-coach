# Monogatari Coach

Monogatari Coach は、小説執筆の企画、設計、執筆、推敲、評価、画像生成、漫画展開までを一貫して支援するリポジトリです。ルートの `README.md` は最短の入口に絞り、詳しい説明は `docs/` 配下へ整理しています。

## Docs

- [Docs Index](docs/index.md)
- [Getting Started](docs/getting-started/index.md)
- [Image Generation](docs/image-generation/index.md)
- [Manga prompt IR（YAML・検証・バッチ）](docs/image-generation/manga-prompt-ir.md)
- [Manga tag generation（互換 Step1/Step2・テンプレ）](docs/image-generation/manga-tag-generation.md)
- [Workflow](docs/workflow/index.md)
- [指示出しベースのワークフロー（コピペ用）](docs/workflow/instruction-driven.md)
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
MONOCRI_ENV_VERSION=2026-05-16
NOVELAI_ACCESS_TOKEN=
XAI_API_KEY=
OPENAI_API_KEY=
OPENROUTER_API_KEY=
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok_pro
MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT=grok
MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT=grok_pro
MONOCRI_ILLUSTRATION_MODEL_DEFAULT=
MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT=book_cover
MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT=2k
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=flux
MONOCRI_GROK_MODEL_TIER_DEFAULT=standard
```

不足確認:

```bash
python tools/env_check.py
```

## 主要パス

- ルールの正本:
  [`.rulesync/rules/overview.md`](.rulesync/rules/overview.md)
- 横断概念の正本:
  [`.rulesync/rules/concepts.md`](.rulesync/rules/concepts.md)
- ルール作成規約:
  [`.rulesync/rules/rule-authoring.md`](.rulesync/rules/rule-authoring.md)
- スキルの正本:
  [`.rulesync/skills/`](.rulesync/skills/)
- 人物命名の入口:
  [`.rulesync/skills/character-naming/SKILL.md`](.rulesync/skills/character-naming/SKILL.md)
- 創作技法テンプレートの正本:
  [`_how_to.example/`](_how_to.example/)
- ローカル試行:
  [`tools_temp/README.md`](tools_temp/README.md)
- ユーザ用 Python（`_how_to/skills/` 付随）:
  [`_how_to/tools/README.md`](_how_to/tools/README.md)
- ユーザスキル（プラグイン相当）:
  [docs/workflow/user-skills.md](docs/workflow/user-skills.md)

## 日常運用でよく使うコマンド

初回化:

```bash
uv run python howto_init.py
```

ルール再生成:

```bash
rulesync generate
```

`.rulesync/` 側の正本を更新したあとに実行します。実行後は `AGENTS.md` / `CLAUDE.md` の差分が、LLM 別入口として意図どおりか確認します。

文字数確認:

```bash
uv run python tools/novel_char_count.py novels/NNN_作品タイトル
```

Grok dry-run:

```bash
python tools/image_provider_generate.py --provider grok --params tools/fixtures/grok_params.tier_test.example.json --dry-run
```

## ライセンス

MIT License
