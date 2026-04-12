# Getting Started

Monogatari Coach をローカルで使い始めるための最短手順です。

## 1. rulesync を入れる

Node.js と `rulesync` を導入します。

- Node.js:
  https://nodejs.org/en/download
- rulesync:
  https://github.com/dyoshikawa/rulesync

```bash
npm install -g rulesync
```

## 2. uv を入れる

Python スクリプト運用は `uv` 推奨です。

- uv 公式:
  https://docs.astral.sh/uv/

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 3. 初回セットアップ

プロジェクトルートで実行します。

```bash
uv run python howto_init.py
```

この処理で次が整います。

- `_how_to.example/` から `_how_to/` を未作成時にコピー
- `.env.example` から `.env` を未作成時にコピー

## 4. `.env` を埋める

最低限、使う画像プロバイダに応じてトークンを設定します。

```dotenv
NOVELAI_ACCESS_TOKEN=
XAI_API_KEY=
MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=forge
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=flux
MONOCRI_GROK_MODEL_TIER_DEFAULT=standard
```

`.env` の各既定値の意味は [Image Generation](../image-generation/index.md) を参照してください。

## 5. よく使うコマンド

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

## 次に読む

- 画像生成設定:
  [../image-generation/index.md](../image-generation/index.md)
- ワークフロー全体:
  [../workflow/index.md](../workflow/index.md)
- 運用上の正本:
  [../../.rulesync/rules/overview.md](../../.rulesync/rules/overview.md)
