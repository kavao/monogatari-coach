---
root: true
targets: ["*"]
description: "Monogatari Coach の安全規則とタスクルーター"
globs: ["**/*"]
---

# Monogatari Coach ルートルーター

`overview.md`を読み込みました！

このファイルは安全規則と参照先だけを定義する。長い手順はスキル、詳細な横断仕様は `workflow-specification.md`、人間向け操作は `docs/` を参照する。

## 第0層: 緩和不可の規則

1. 作業前に、依頼内容・対象パス・変更種別・必要なスキルを分類する。
2. 秘密情報（`.env`、トークン、認証情報）を読込・出力・ログ記録・生成物へ混入させない。
3. 正本と生成物を区別し、`AGENTS.md` / `CLAUDE.md` などの生成物を主編集しない。
4. 無関係な既存変更を保持し、破壊的操作は対象と影響を確認してから行う。
5. 明示されない外部送信、git add / commit / push、課金を伴う本番生成は実行しない。
6. `.rulesync/`、`docs/`、`_how_to.example/`、`tools/` の役割を混同しない。
7. 成果物の完了は正本への書込みと確認後だけ報告する。
8. 各セッションで現在のモードと次手を短く報告し、査証ログを追記する。対象作品の config.md に `AUDIT_LOG | OFF` があるときは追記しない（ユーザーが明示した追記は除く）。

## 条件別ルーティング

| 条件 | 必ず参照する正本・スキル |
| --- | --- |
| ルール、スキル、入口生成物を変更する | `rule-authoring.md`、`concepts.md`、`docs/rulesync.md` |
| `docs/` を変更する | `docs-writing.md` |
| 企画、設定、人物、世界観を整える | `novel-planning`、`novel-character-profile` |
| 原資料を作品形式へ展開する | `source-material-intake`、`novel-code-allocate` |
| 小説本文を書き、追記し、清書する | `novel-project-readiness`、`novel-text-file-output`、必要に応じ `novel-refinement-output` |
| キャラクター、漫画、挿絵、表紙を扱う | `manga-prompt-ir`、対象の Tag / Illustration / Cover スキル |
| 画像を生成する | `forge-txt2img` と `image-provider`。dry-run 後、ユーザー承認を得る |
| 下読み、採点、整合性監査をする | `novel-reader-output` または `novel-evaluation-output` |
| 読み進み感想を場面ごとに残す | `novel-reader-walk` |
| 計画、査証ログ、日記を更新する | `workspace-audit-log`、必要に応じ `workspace-diary` |

## 優先順位

1. 第0層
2. 対象パスに最も近いルール
3. 選択したスキル
4. このルーターと `concepts.md`
5. `workflow-specification.md`
6. `docs/` と `_how_to.example/`

下位の文書やスキルは第0層を緩和してはならない。
