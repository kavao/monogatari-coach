---
targets: ["*"]
description: "Monogatari Coach の常時適用する最小概念正本"
globs: [".rulesync/**", "tools/**", "docs/**", "_workingspace/**", "rulesync.jsonc", "sync_rules.py", "readme.md"]
---

# 概念正本

このファイルは、すべての作業で必要な最小の判断だけを置く。作品・画像・出版の詳細は [ワークフロー詳細仕様](workflow-specification.md) と該当スキルを正とする。

## 正本と副本

- ルール・スキルの正本は `.rulesync/rules/` と `.rulesync/skills/`、`AGENTS.md` / `CLAUDE.md` は生成物である。
- 創作技法の雛形は `_how_to.example/`、`_how_to/` はユーザー調整領域である。
- 操作説明は `docs/`、チャットは要約である。
- 小説本文は `novels/<作品>/_novel_text/novel_text*.md`、キャラクタータグは `tag/characters/*.yaml`、漫画ページは `manga/pages/*.yaml`、挿絵ページは `illustrations/pages/*.yaml` を正本とする。
- 正本を更新できる場合、副本だけを直して完了扱いにしない。生成物を変えたいときは先に正本を変え、再生成する。

## 完了扱い条件

- ファイル成果物は、正しい正本パスへの書込み後に再読込または対応する検証で確認してから完了と報告する。
- 画像生成は、ユーザー承認後の本番実行と指定保存先での実ファイル確認を満たしてから完了とする。
- 文字数を報告・記録するときは `tools/novel_char_count.py` の集計値を使う。
- 作業事実は `_workingspace/log/YYYYMM.md` へ追記し、次回以降も使う判断理由は `_workingspace/diary/YYYYMM.md` へ追記する。

## Plan Mode の完了

- **企画完了 = Gate A ∧ Gate B**。`novel_project_check` の OK（骨格）だけでは完了としない。
- Gate A は必須ファイル・scaffold・character lint・project check。Gate B は作品タイプに応じた知識読込・設計の厚さ・洗練・`_meta.md` への実施記録。
- 手順の正本はスキル **`novel-planning`**。横断の厚さ・命名は `workflow-specification.md` の関連仕様を参照する。

## ルールとドキュメント

- ルール・スキル更新は `.rulesync/` を主編集先とし、`rule-authoring.md` に従う。
- 人間向け操作説明は `docs/` に置き、`docs-writing.md` に従う。
- `tools/` は共有・正規運用の Python ツール、`tools_temp/` は短命な試行に使う。
- `_how_to/` の恒久的なルール化・雛形更新は、ユーザーの明示依頼と `_how_to.example/` 側の検討を要する。

## 詳細仕様の参照先

| 作業 | 正本 |
| --- | --- |
| Plan / Source Material / Writing / Refinement | 該当スキルと `workflow-specification.md` |
| Tag / Manga / Illustration / Cover / Publishing | 該当スキルと `workflow-specification.md` |
| Reader / Editor Score / Consistency Audit | `novel-reader-output` / `novel-evaluation-output` |
| Rulesync | `docs/rulesync.md` と `rule-authoring.md` |
