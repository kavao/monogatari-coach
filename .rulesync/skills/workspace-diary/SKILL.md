---
name: workspace-diary
description: >-
  _workingspace/diary/(YYYYMM).md 横断ナレッジ日記を tools/workspace_audit_log.py diary で追記専用運用する。
  査証ログと同様に既存行の上書き・削除は行わない。月次シャーディング。
targets: ["*"]
---

## 目的

`.rulesync/rules/concepts.md` の **「プロジェクト・インテリジェンス」** に従い、**作品を横断する**好み・パターン・方針・学びを **`_workingspace/diary/(YYYYMM).md` にのみ追記**し、履歴を機械的に保証する。

- **査証ログとの差**: **査証ログ**はセッションごとの作業の事実記録。**日記**は「なぜそうしたか」「このリポジトリではこう決めた」など、**再利用したいナレッジ**向け（重複しうるが、意図が違う）。
- **追記型のみ**: 新規エントリは **`tools/workspace_audit_log.py diary append`** で追加する。スクリプトは **`open(..., "a")` 以外で日記本文を書かない**（新規月ファイルのヘッダ初回だけ同じ追記処理内で行う）。
- **月次シャーディング**: ファイル名は査証ログと同じく **`YYYYMM.md`**（例: `202604.md`）。誤って1か月分を壊しても他月が残る。
- **エントリの1行形式（公式）**（査証ログと同一）:
  `- YYYY-MM-DD HH:MM: 本文`
  本文に改行を含めない（複数行貼り付けは空白で連結される）。

## いつ追記するか

- ルール変更・ツール方針・ユーザー好みの確定・繰り返し説明を減らせる洞察など、**次のセッションでも効かせたい**とき。
- 査証ログに書いた作業の補足として「背景だけ日記」に残す、などの使い分けも可。

## 実行方法

リポジトリルート（`monocri/`）で。

**1件追記**（日時は実行時刻。追記先は「今日の年月」のファイル）:

```bash
python tools/workspace_audit_log.py diary append "Forge は FLUX 時に CFG を UI と揃える方針で固定した。"
```

**標準入力から**:

```bash
echo "本文" | python tools/workspace_audit_log.py diary append
```

**追記先の月を指定**:

```bash
python tools/workspace_audit_log.py diary append --year-month 202604 "本文"
```

**エントリの日時だけ変える**:

```bash
python tools/workspace_audit_log.py diary append --year-month 202604 --at "2026-04-11 15:30" "本文"
```

**今月（または指定月）の日記ファイルの絶対パス**:

```bash
python tools/workspace_audit_log.py diary path
python tools/workspace_audit_log.py diary path --year-month 202604 --json
```

**体裁チェック**（読み取り専用。`diary/` が未作成なら OK とみなす）:

```bash
python tools/workspace_audit_log.py diary verify
python tools/workspace_audit_log.py diary verify --strict
```

**検証のみ**（書き込まない）:

```bash
python tools/workspace_audit_log.py diary append --dry-run "本文"
```

## 禁止・非推奨

- 日記で **既存行の削除・並べ替え・中間挿入・全文置換** を行うこと。誤記の訂正が必要なときは、**訂正エントリを追記**して理由を残す運用を推奨。
- **`workspace_audit_log.py diary` を使わず** エディタで日記ファイルを**全文上書き**しない（LLM の誤動作で履歴が消えるリスクが高い）。通常は本ツールで追記する。

## エージェント向け運用

- 横断ナレッジを残すタイミングで **`diary append` を実行**する。
- 査証ログ（`append`）と混同しない。作業の事実は査証ログ、再利用したい方針は日記、の切り分けを推奨。

## 関連パス

- スクリプト: `tools/workspace_audit_log.py`（サブコマンド `diary append` / `diary path` / `diary verify`）
- 保存先: `_workingspace/diary/YYYYMM.md`
- 概念正本: `.rulesync/rules/concepts.md`（プロジェクト・インテリジェンス）
- 入口ルール: `.rulesync/rules/overview.md`（日記・査証ログ）
- 姉妹スキル: **`workspace-audit-log`**（`_workingspace/log/`）
