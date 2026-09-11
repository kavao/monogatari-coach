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
- 小説本文の初稿・場面追記は、対象ファイルに対する `tools/novel_punctuation_metrics.py --gate` が成功してから完了とする。`writing_bridge` の `publish` 後は `report.json` の句読点記録を正とし、失敗でも本文は戻さない。未達なら完了報告しない。
- 作業事実は `_workingspace/log/YYYYMM.md` へ追記し、次回以降も使う判断理由は `_workingspace/diary/YYYYMM.md` へ追記する。対象作品の config.md に `AUDIT_LOG | OFF` があるときは査証ログを追記しない。
- 読み進み（Reader Walk）は作品評価を採点せず、既読範囲の感想を `_reader/walk/<session_id>/journal.md` へ追記し、同じセッションディレクトリの `state.md` を更新してから完了とする。定量化を有効にした場合だけ、評価点ではないペルソナ反応メタデータを同じ `journal.md` に残し、完了前に `tools/novel_reader_walk_check.py` で検証する。未読を先読みしない。`walk/` 直下の旧形式は移行時だけ扱う。

## METRON V1 修復不変条件

- METRON の `BeatMissing` はマーカー／coverage 異常または承認済みの `missing_span_ratio`（文字数比の極端な短さ）、`BeatThin` は別統計の `beat_thin_ratio`（段落・会話の充足率）と構造予算で判定する。両方の閾値を同じ値にしない。`BeatThin` の自動修復は計画の段落下限または会話下限の未達に限る。校正典型値だけの未達は指摘を残し、自動修復しない。
- 分量バーは構造バーと別に置く。シーンは `generation.chars_floor`（既定 4000字）、Beat は `chars_hint` を床とする。未達は `TooShort` とし、Deepen（ニュアンス深化）のみで自動修復する。末尾再生成には使わない。writing_bridge の context は下限（検査）と指示目標（助言）を出す。指示目標未達だけでは `TooShort` にしない。
- Writer / Deepen 指示は床以上の指示目標を出す（既定 1.4 倍。極小床では丸めで床と同じになりうる）。水増しは禁止する。深化の対象は手順・制度・選択に加え、感情の変化と身体の変化、感覚・内面・会話とする。すでに書いた内容の言い換えは対象にしない。
- Expand / Deepen は現在の出来事・結末・視点を変更せず、元文残存率が `expand_retention_threshold` 未満の候補、同一本文、文字数が増えていない候補、新規文が既存文または他の新規文と高類似の候補を適用しない。同一 Beat の試行は2回を上限とする。
- 必須修復または適格な追加候補があるときだけ、Beat マーカーを保持した結合校正を最大1回行い、BeatPlan 順を変えた候補は棄却する。校正後は正規化済み本文で再計測し、シーン床未達なら適格Beatだけを追加で Deepen する。必須修復も追加候補も無いときは結合校正を出さず、適格が無ければ `__scene_floor__` で止め、同一runへ新しい稿は受けない。既存の `FINAL.md` は上書きせず、採用稿から Beat / fact マーカーを除去して保存する。

## CHRONOS P0 不変条件

- 時刻は制約であり、日付は任意である。`after` / `before` だけで検査できる。
- 検査は決定的コード（P0 は CHR001、人物状態は CHR010〜013）で行い、LLM に判定を委ねない。
- `chronos check` は `world.md` や `_novel_text` を副作用で書き換えない。抽出の上書きは差分提案と作者承認が揃うまで行わない。
- 執筆完了ゲートにはしない。フラグ OFF / P0 単体では METRON の本文計測とも自動接続しない。執筆工程への接続は `writing_bridge` が行う。

## CHRONOS 人物状態（P0.5）

- 作品が `character_state.dimensions` で `enum` / `bool` / `loc_ref` を宣言したときだけ状態検査が有効になる。コアはジャンル語を持たない。
- 循環または同一人物の未確定順序では状態を捏造しない。CHR012 は `rules.CHR012` と bind が揃った作品だけの opt-in である。
- 検査は挿絵・タグ YAML を読取専用とし、本文や挿絵を書き換えない。執筆完了ゲートにはしない。

## 作品単位の METRON / CHRONOS / AUDIT_LOG フラグ

- 人間向け正本は対象作品の config.md にある「## 基本情報」表。METRON と CHRONOS と AUDIT_LOG は独立した ON / OFF 値として読む。
- METRON / CHRONOS は、config.md または対象行がない場合は OFF。AUDIT_LOG は対象行がない場合、および config.md 未作成の場合は ON（従来の追記を維持する）。壊れた既存 config.md は設定エラーとする。
- 未知値・重複キー・既存 config.md の読込失敗は設定エラーとし、黙って既定値にしない。
- フラグはエージェントの自動ワークフロー起動判定にだけ使う。ユーザーが明示した metron_cli.py / chronos_cli.py / 査証ログ追記はフラグで拒否しない。
- ON の検査結果は本文保存の完了と分けて報告し、METRON / CHRONOS の欠落や失敗で本文完了を取り消さない。
- METRON ON は当該作品の writing_bridge 場面作業（修復と正本反映）を承認済みと扱う。止めの明示があるときだけ publish しない。CHRONOS ON だけでは正本反映の承認にしない。課金生成・イベント上書き・画像は対象外。

## 執筆接続（writing_bridge）

- METRON / CHRONOS が ON で、対象場面にハッシュ一致の active run があるときは `writing_bridge_cli.py` が検査責任を持つ。同じ版へ `metron_cli.py analyze` / `chronos_cli.py check` を重ねない。
- 同一受領候補の inspect は既存の metrics / spans を再利用する。保存用 run は `inspect --from-run` で本文 hash が一致する observations を流用する。`--from-run` は `run-\d{4,}` に限り、observations 欠落は UNKNOWN_REF、不一致は STALE とする。
- 修復が active のあいだ、C1 未記録は report に残すが inspect を失敗にしない。完了後と保存前は従来どおり未記録で止める。CHRONOS ON の `publish` は C1 成功前に正本を書かない。
- 正本反映は `permissions.publish` がある run の `publish` だけを使う。METRON ON の場面作業では反映依頼済みとみなし、CLI の `--allow-publish` は技術ゲートとして残す。手編集で `_novel_text` を置換しない。`FINAL.md` だけでは完了にしない。
- 清書（rewrite.md）の既定は従来どおり自動計測しない。フラグ OFF と明示 CLI は従来動作を保つ。
- `_meta.md` のストーリー反映は CLI の外で `novel-story-reflection` が行う。

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
| METRON / CHRONOS / AUDIT_LOG | `workflow-specification.md` と `docs/architecture/` |
| 執筆接続 | `writing_bridge` と `docs/architecture/writing-bridge.md` |
| Rulesync | `docs/rulesync.md` と `rule-authoring.md` |
