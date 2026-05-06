---
name: novel-reader-output
description: >-
  下読み・書評・一般読者の興味判定を novels/.../_reader/ に保存し、
  チャットには判定と要約だけを返す。reader.md / standard_reader.md の参照、
  保存先ファイル名、完了報告の条件を固定する。
targets: ["*"]
---

## 目的

First Reader Mode と Interest Check Mode で、評価結果の所在を曖昧にしない。

横断正本は **`.rulesync/rules/concepts.md`** の「評価出力の保存先」。このスキルは、その保存条件を満たすための実行手順を定める。

## 保存先（必須）

| 種別 | 参照する技法 | 保存先 |
|------|--------------|--------|
| First Reader / 下読み・書評 | `_how_to/reader.md` | `novels/<作品>/_reader/YYYYMMDD_HHMM.md` |
| Interest Check / 一般読者の興味判定 | `_how_to/standard_reader.md` | `novels/<作品>/_reader/interest_YYYYMMDD.md` |

- `YYYYMMDD_HHMM` は実行時刻を使う。
- `_reader/` が無ければ作成する。
- チャット欄に本文を書いただけでは完了ではない。評価本文は必ず上記ファイルへ保存する。

## First Reader の内容

`_how_to/reader.md` に従い、最低限次を保存する。

- 日付・時刻
- 対象作品ID／作品名／章・対象範囲
- 判定（合格／不合格、または読むべき／読まなくてよい）
- 5段階評価
- 評価観点（キャラクター、プロット、文章力、わかりやすさ、独創性など）
- 改善ポイント

## Interest Check の内容

`_how_to/standard_reader.md` に従い、最低限次を保存する。

- ペルソナ設定
- タイトル、冒頭3行、最初の1ページの第一印象
- 判定（継続読了／読み飛ばし／ブラウザバック等）
- 興味のフック、または離脱の決定打

## チャットで返すもの

チャットには、保存した評価本文の要約だけを返す。

- 判定
- 重要な理由を1〜3行
- 改善ポイントの要約
- 保存先ファイルパス

## 査証ログとの関係

- `_reader/` は評価本文の正本。
- `_workingspace/log/` は「評価を実施し、どのファイルへ保存したか」という作業事実だけを追記する。
- 査証ログの追記はスキル **`workspace-audit-log`** と `tools/workspace_audit_log.py append` に従う。

## 関連

- 概念正本: `.rulesync/rules/concepts.md`（評価出力の保存先）
- 入口ルール: `.rulesync/rules/overview.md`（First Reader Mode / Interest Check Mode）
- 操作説明: `docs/workflow/instruction-driven.md`
