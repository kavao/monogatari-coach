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
- [Community](docs/community/index.md)

## Quick Start

以降のコマンドは、clone したリポジトリのルートで実行します。

1. リポジトリを取得

```bash
git clone https://github.com/kavao/monocri.git
cd monocri
```

2. Node.js を導入

Node.js 同梱の Corepack 経由で `pnpm` を都度呼び出します。`rulesync` や `pnpm` のグローバルインストールは不要です。

3. `uv` を導入して初回セットアップ

```bash
uv sync
uv run python howto_init.py
```

4. ルールを再生成

```bash
corepack pnpm dlx rulesync generate

# 後方互換ラッパーを使う場合
uv run python sync_rules.py
```

5. `.env` を整える

`howto_init.py` が `.env.example` から `.env` を未作成時にコピーします。画像生成を使う場合は、使う provider に応じて `.env` に API キーを入れます。

```dotenv
NOVELAI_ACCESS_TOKEN=
XAI_API_KEY=
```

`NOVELAI_ACCESS_TOKEN` / `XAI_API_KEY` の取得方法と provider 別の設定は [Image Generation](docs/image-generation/index.md) を参照してください。

不足確認:

```bash
python tools/env_check.py
```

`.env.example` が見つからない場合は、別フォルダで実行していないか確認します。

```powershell
Get-Location
Get-ChildItem -Force .env*
git status --short
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
corepack pnpm dlx rulesync generate

# 後方互換ラッパーを使う場合
uv run python sync_rules.py
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
