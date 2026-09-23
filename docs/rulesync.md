# Rulesync の固定運用

このガイドを読むと、Monogatari Coach のルールを固定版 Rulesync 15.0.1 で安全に生成・確認できます。Windows x64 の単体バイナリを使うため、グローバル npm や Node.js の版に日常運用は依存しません。

## 初回取得

リポジトリのルートで、検証付きの単体バイナリを取得します。ダウンロード先は Git 管理外の `.tools/` です。

```powershell
python tools/install_rulesync.py
```

この処理は固定 URL から `rulesync-windows-x64.exe` を取得し、SHA-256 と `rulesync --version` が 15.0.1 と一致したときだけ配置します。管理者権限や PATH の変更は不要です。

## ルールの生成

`.rulesync/` の正本を変更した後は、まず変更予定を確認します。

```powershell
# 確認: 更新される生成物だけを表示する
python tools/rulesync.py generate --dry-run

# 本番: 生成物を同期する
python tools/rulesync.py generate

# 確認: 生成物が正本と一致していることを検査する
python tools/rulesync.py generate --check
```

生成物の `AGENTS.md`、`CLAUDE.md`、各ツール設定は直接編集しません。内容を変えるときは `.rulesync/rules/` または `.rulesync/skills/` を編集してから再生成します。通常の generate は削除を実行しません。不要な生成物を消す作業は、対象を確認した別作業として扱います。

### `agentsmd` の既知通知

Monocri は `agentsmd` を `AGENTS.md` の所有 target として使います。この target は skills・subagents・MCP を直接出力できませんが、他の target にはそれらが必要です。したがって `tools/rulesync.py` は、この意図された非対応を知らせる3行だけを非表示にします。

`--simulate-skills` や `--simulate-subagents` は有効にしません。疑似定義が `AGENTS.md` を膨らませ、軽量ルーター化の目的に反するためです。これ以外の出力、未知の警告、エラー、終了コードはそのまま表示・返却されます。

## 互換コマンド

以前のコマンドを使う環境では、次も同じ固定バイナリで全 target を生成します。

```powershell
python sync_rules.py
```

## 故障時

取得物が壊れた、または再取得したいときは、次を実行します。

```powershell
python tools/install_rulesync.py --force
```

`rulesync update` や `latest` URL は使いません。Rulesync の版を更新する場合は、リリース、SHA-256、隔離生成の差分を改めて確認します。

変更後の確認コマンド、コミット前の総合ゲート、実クライアント向けの代表プロンプトは [開発者向け検証コマンド](developer-verification.md) を参照してください。
