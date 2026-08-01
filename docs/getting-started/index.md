# Getting Started

このガイドを読むと、Monogatari Coach をローカル環境で動かすための初期設定が完了します。所要時間は 10〜15 分が目安です。

Monogatari Coach は、チャットへの指示だけで小説の企画・執筆・画像生成までを進めるフレームワークです。AI が作業を担い、ユーザーは「何を作るか」の判断に集中できます。

## 1. リポジトリを clone する

Monogatari Coach のリポジトリを取得し、以降のコマンドを実行する場所へ移動します。

```bash
git clone https://github.com/kavao/monocri.git
cd monocri
```

このガイドのコマンドは、すべて `monocri` のリポジトリルートで実行します。`.env.example`、`howto_init.py`、`tools/` が見える場所です。

## 2. uv を入れる

Python スクリプト運用は `uv` 推奨です。

- uv 公式:
  https://docs.astral.sh/uv/

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 3. Python 環境を整える

依存関係と `.venv` を作ります。エディタ（Cursor/VSCode）の静的解析が別の Python を見ている場合も、この手順で警告を減らせます。

```bash
uv sync
```

エディタで `インポート "pydantic" を解決できませんでした` のような警告が残る場合は、コマンドパレットで `Developer: Reload Window` を実行します。

`.venv` が使えているかだけ確認したい場合は、次を実行します。

```powershell
.\.venv\Scripts\python.exe -c "import pydantic; print(pydantic.__version__)"
```

## 4. 初回セットアップ

プロジェクトルートで実行します。

```bash
uv run python howto_init.py
```

この処理で次が整います。

- `_how_to.example/` から `_how_to/` を未作成時にコピー
- `.env.example` から `.env` を未作成時にコピー

既に `_how_to/` や `.env` がある場合は上書きしません。`.env.example` がない場所で実行した場合、`.env` は作れません。

`.env.example` / `.env` が見つからない場合は、まず作業場所を確認します。

```powershell
Get-Location
Test-Path .env.example
Test-Path .env
Get-ChildItem -Force .env*
git status --short
```

`Test-Path .env.example` が `False` の場合は、clone したフォルダとは別の場所で実行しているか、取得した配布物に `.env.example` が含まれていない可能性があります。

## 5. ルールを再生成する

`.rulesync/` のルール・スキルから、AI ツールごとの入口ファイルを生成します。固定版 Rulesync 15.0.1 の単体バイナリを使うため、Node.js・pnpm・グローバル npm は不要です（詳細は [Rulesync](../rulesync.md)）。

```powershell
python tools/install_rulesync.py
python tools/rulesync.py generate --dry-run
python tools/rulesync.py generate
python tools/rulesync.py generate --check
```

## 6. `.env` を埋める

最低限、使う画像プロバイダに応じてトークンを設定します。

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
MONOCRI_FORGE_MODEL_FAMILY_DEFAULT=
MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO=manga_b5_portrait
MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT=grok_pro
MONOCRI_ILLUSTRATION_MODEL_DEFAULT=
MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT=book_cover
MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT=2k
```

`.env` の各既定値、`NOVELAI_ACCESS_TOKEN` / `XAI_API_KEY` の取得先、provider の使い分けは [Image Generation](../image-generation/index.md) を参照してください。

テンプレート更新後の不足確認:

```bash
python tools/env_check.py
```

## 7. 最小成功チェック

初回導入は、次が通ればひとまず成功です。

```bash
uv sync
uv run python howto_init.py
python tools/install_rulesync.py
python tools/rulesync.py generate
python tools/env_check.py
```

`env_check.py` が API キー不足を出す場合でも、まだ画像生成をしないなら設定待ちとして扱えます。使う provider が決まったら `.env` にキーを入れて再実行します。

## 8. よく使うコマンド

初回化:

```bash
uv run python howto_init.py
```

ルール再生成:

```powershell
python tools/rulesync.py generate --dry-run
python tools/rulesync.py generate
python tools/rulesync.py generate --check
```

`.rulesync/` のルール・スキルを更新したあとに実行します。生成後は `AGENTS.md` / `CLAUDE.md` の差分を確認し、入口ファイルに意図しない肥大化や欠落がないか見ます。

文字数確認:

```bash
uv run python tools/novel_char_count.py novels/NNN_作品タイトル
```

## 9. 新規作品を始める

初期設定が終わったら、1コマンドで新規作品フォルダを準備できます。

```bash
# 作品名を渡すと採番→フォルダ作成→scaffold→状態確認まで一括実行
python tools/novel_onboard.py "作品タイトル"

# 実行前にフォルダパスと採番だけ確認する
python tools/novel_onboard.py "作品タイトル" --dry-run
```

実行後に `[Plan Mode] → 企画書を作成してください（proposal.md から）` と出たら、チャットで「企画書を作成してください」と伝えるだけで制作が始まります。

---

## 次に読む

- チャットからどう指示するか知りたい → [ワークフロー（指示テンプレ付き）](../workflow/instruction-driven.md)
- どちらの進め方が合うか確認したい → [ワークフロー入口（資料先出し vs 対話先出し）](../workflow/index.md)
- ルール変更後の確認やコミット前ゲート → [開発者向け検証コマンド](../developer-verification.md)
- 詰まったとき → [トラブルシューティング](../workflow/troubleshooting.md)
- 画像生成の設定を行いたい → [Image Generation](../image-generation/index.md)
- リポジトリ構成を把握したい → [Project Structure](../project-structure/index.md)
