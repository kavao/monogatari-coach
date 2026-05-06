# Getting Started

このガイドを読むと、Monogatari Coach をローカル環境で動かすための初期設定が完了します。所要時間は 10〜15 分が目安です。

Monogatari Coach は、チャットへの指示だけで小説の企画・執筆・画像生成までを進めるフレームワークです。AI が作業を担い、ユーザーは「何を作るか」の判断に集中できます。

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
MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT=novelai
MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT=grok_pro
MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT=grok_pro
MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT=grok
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=
MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO=manga_b5_portrait
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

- チャットからどう指示するか知りたい → [ワークフロー（指示テンプレ付き）](../workflow/instruction-driven.md)
- 画像生成の設定を行いたい → [Image Generation](../image-generation/index.md)
- リポジトリ構成を把握したい → [Project Structure](../project-structure/index.md)
