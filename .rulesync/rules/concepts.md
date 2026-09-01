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
- 読み進み（Reader Walk）は作品評価を採点せず、既読範囲の感想を `_reader/walk/<session_id>/journal.md` へ追記し、同じセッションディレクトリの `state.md` を更新してから完了とする。定量化を有効にした場合だけ、評価点ではないペルソナ反応メタデータを同じ `journal.md` に残し、完了前に `tools/novel_reader_walk_check.py` で検証する。未読を先読みしない。`walk/` 直下の旧形式は移行時だけ扱う。

## METRON V1 修復不変条件

- METRON の `BeatMissing` はマーカー／coverage 異常または承認済みの `missing_span_ratio`（文字数比の極端な短さ）、`BeatThin` は別統計の `beat_thin_ratio`（段落・会話の充足率）と構造予算で判定する。両方の閾値を同じ値にしない。
- 分量バーは構造バーと別に置く。シーンは `generation.chars_floor`（既定 4000字）、Beat は `chars_hint` を床とする。未達は `TooShort` とし、Deepen（ニュアンス深化）のみで自動修復する。末尾再生成には使わない。
- Writer / Deepen 指示は床より多めの指示目標を出す。水増しは禁止する。深化の対象は手順・制度・選択に加え、感情の変化と身体の変化、感覚・内面・会話とする。すでに書いた内容の言い換えは対象にしない。
- Expand / Deepen は現在の出来事・結末・視点を変更せず、元文残存率が `expand_retention_threshold` 未満の候補、同一本文、文字数が増えていない候補、新規文が既存文または他の新規文と高類似の候補を適用しない。同一 Beat の試行は2回を上限とする。
- Beat 修復後は、Beat マーカーを保持した結合校正を最大1回行い、BeatPlan 順を変えた候補は棄却する。校正後は正規化済み本文で再計測し、シーン床未達なら他 Beat も Deepen する。既存の `FINAL.md` は上書きせず、採用稿から Beat / fact マーカーを除去して保存する。

## CHRONOS P0 不変条件

- 時刻は制約であり、日付は任意である。`after` / `before` だけで検査できる。
- 検査は決定的コード（P0 は CHR001）で行い、LLM に判定を委ねない。
- `chronos check` は `world.md` や `_novel_text` を副作用で書き換えない。抽出の上書きは差分提案と作者承認が揃うまで行わない。
- 執筆完了ゲートにはしない。METRON の本文計測とも自動接続しない。

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
| Reader / Editor Score / Consistency Audit / Reader Walk | `novel-reader-output` / `novel-evaluation-output` / `novel-reader-walk` |
| METRON / CHRONOS | `workflow-specification.md` と `docs/architecture/` |
| Rulesync | `docs/rulesync.md` と `rule-authoring.md` |
