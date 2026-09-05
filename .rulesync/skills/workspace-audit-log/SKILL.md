---
name: workspace-audit-log
description: >-
  _workingspace/log/(YYYYMM).md 査証ログを tools/workspace_audit_log.py で追記専用運用する。
  既存行の上書き・削除は行わない。
targets: ["*"]
---

## 目的

`.rulesync/rules/workflow-specification.md` の **「プロジェクト・インテリジェンス」** に従い、会話・作業の記録を **`_workingspace/log/(YYYYMM).md` にのみ追記**し、履歴を機械的に保証する。

- **追記型のみ**: 新規エントリは **`tools/workspace_audit_log.py append`** で追加する。スクリプトは **`open(..., "a")` 以外でログ本文を書かない**（新規月ファイルのヘッダ初回だけ同じ追記処理内で行う）。
- **ファイル命名**: 西暦4桁＋月2桁、`202604.md` のように **ゼロ埋め2桁の月**。
- **エントリの1行形式（公式）**:
  `- YYYY-MM-DD HH:MM: 本文`
  本文に改行を含めない（複数行貼り付けは空白で連結される）。

## いつ追記するか

- **会話（セッション）ごと**に、更新したファイル・実施したモード・次に望ましいことを1エントリにまとめる（既存の査証ログの書き方例に準拠）。
- 対象作品の `config.md` に `AUDIT_LOG | OFF` があるときは、自動追記しない。行なし、または `config.md` 未作成は ON（従来どおり追記する）。
- **抑止は `--novel` を付けたときだけ有効。** 作品作業の自動追記は必ず `--novel novels/<作品>` を付ける。対象作品がない横断作業だけ省略してよい。
- ユーザーが「査証ログを書いて」と明示したときは OFF でも追記する（`--force`）。日記は本フラグの対象外。

## 何を記録するか

査証ログは、後から作業事実を確認できるようにするための履歴である。必要に応じて次を1エントリにまとめる。

- 重要な実装パス
- ユーザーの好みとワークフロー
- プロジェクト特有のパターン
- 既知の課題
- プロジェクト決定の変化
- ツールの使用パターン
- 次に望ましい作業

## 文字数を併記するとき

執筆・推敲の記録に**文字数**を書く場合は、`tools/novel_char_count.py` の**集計値**を根拠として併記する（定義はスキル `novel-char-count` に従う）。

## 実行方法

リポジトリルート（`monocri/`）で。

**1件追記**（日時は実行時刻。追記先は「今日の年月」のファイル）:

```bash
python tools/workspace_audit_log.py append --novel novels/<作品> "関連ファイル（…）を更新。次は…が望ましい。"
```

`AUDIT_LOG | OFF` の作品では、上の `--novel` 指定により追記せず終了する。ユーザー明示の追記だけ `--force` を付ける。

**標準入力から**（長文に便利）:

```bash
echo "本文" | python tools/workspace_audit_log.py append --novel novels/<作品>
```

**追記先の月を指定**（例: 2026年4月のファイルへ）:

```bash
python tools/workspace_audit_log.py append --novel novels/<作品> --year-month 202604 "本文"
```

**エントリの日時だけ変える**（ファイルは `--year-month`、行の日付は `--at`）:

```bash
python tools/workspace_audit_log.py append --novel novels/<作品> --year-month 202604 --at "2026-04-11 15:30" "本文"
```

**今月（または指定月）のログファイルの絶対パス**:

```bash
python tools/workspace_audit_log.py path
python tools/workspace_audit_log.py path --year-month 202604 --json
```

**体裁チェック**（読み取り専用。移行前の手書きログは WARN になりうる）:

```bash
python tools/workspace_audit_log.py verify
python tools/workspace_audit_log.py verify --strict
```

- 既定: 先頭行が `# 査証ログ`、本文は `- ` で始まることを確認。公式1行形式でない行は **WARN**。
- `--strict`: 各行を `- YYYY-MM-DD HH:MM: 本文` に厳密照合（エラーで終了）。

**検証のみ**（書き込まない）:

```bash
python tools/workspace_audit_log.py append --novel novels/<作品> --dry-run "本文"
```

## 禁止・非推奨

- 査証ログで **既存行の削除・並べ替え・中間挿入・全文置換** を行うこと（履歴の厳密性が損なわれる）。誤記の訂正が必要なときは、**訂正エントリを追記**して理由を残す運用を推奨。
- `workspace_audit_log.py` を使わず **エディタで直接追記**するのは緊急時のみ。通常は本ツールで形式を統一する。

## エージェント向け運用

- セッション終了前に **可能な限り `append --novel novels/<作品>` を1回実行**し、査証ログを更新する。`AUDIT_LOG | OFF` ならスキップしてよい。
- チャットに「査証ログを書いた」と書くだけで済ませず、**実際にコマンドを実行したか**を作業フローに含める（実行不能な環境のみ、その旨をチャットに明記）。
- `_workingspace/plans/*.md` のチェックリストを持つ計画を実行した場合、**査証ログ追記の前に**計画書の該当タスクを `- [x]` へ更新し、査証ログ本文に「どの計画のどの項目を完了にしたか」を含める（概念正本: `.rulesync/rules/workflow-specification.md`「計画書チェック更新ゲート」）。

## 関連パス

- スクリプト: `tools/workspace_audit_log.py`（`append` / `path` / `verify` は査証ログ用）
- 保存先: `_workingspace/log/YYYYMM.md`
- 概念正本: `.rulesync/rules/workflow-specification.md`（プロジェクト・インテリジェンス）
- 入口ルール: `.rulesync/rules/workflow-specification.md`（プロジェクト・インテリジェンス）
- **横断ナレッジ日記**（別スキル）: `workspace-diary` — `workspace_audit_log.py diary append` などで `_workingspace/diary/YYYYMM.md` へ追記
