---
name: novel-planning
description: >-
  新規作品または既存作品の企画・設計フェーズで、proposal.md、
  design_specification.md、config.md、character.md、world.md、_meta.md などを揃え、
  執筆前確認へつなげる。資料不足時の作成順と確認観点を固定する。
  Plan 完了は Gate A（骨格）と Gate B（知識・厚さ）の両方を満たす。
targets: ["*"]
---

## 目的

Plan Mode で、執筆前に必要な Monogatari Coach ファイルを揃え、「迷わず書ける状態」にする。

このスキルは、企画・設計・人物・世界観・メタ情報を整える作業手順を定める。執筆前の機械確認は **`novel-project-readiness`** を併用する。

**完了の定義**: `novel_project_check` の OK（Gate A）だけでは企画完了としない。Gate B（知識読み込み・設計の厚さ・洗練・実施記録）を満たしてから完了報告する。短い正本は `.rulesync/rules/concepts.md`「Plan Mode の完了」。

## 使う場面

- ユーザーが「企画書と設計書を作って」「新しい小説として起こして」などと指示した。
- Source Material Intake 後、展開済み資料を洗練したい。
- 既存作品の `proposal.md` / `design_specification.md` / `character.md` / `world.md` が不足または薄い。

## 作成・確認するもの

| ファイル | 役割 |
|----------|------|
| `proposal.md` | 作品名、ログライン、ターゲット層、あらすじ、キャラクター紹介、魅力 |
| `design_specification.md` | テーマ、コンセプト、章構成（厚さは Gate B）、ストーリー相関図、執筆スケジュール |
| `config.md` | novel_ID、writer_code、作品名、作者名、ジャンル、キーワード、METRON / CHRONOS の ON / OFF |
| `character.md` | 登場人物のプロフィール、課題、目的、口調、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術、組織 |
| `_meta.md` | 進捗、伏線、次回タスク、**Gate B 記録**、外部投稿用情報 |
| `_meta.yaml` | 画像生成の機械可読設定（現行: NovelAI ポーション）。雛形は `_how_to.example/_meta.yaml.example` |
| `_novel_text/`, `_reader/` | 本文と評価の保存先ディレクトリ |

## 分類（作業開始時に明記する）

分類軸を分けて判定し、チャットまたは `_meta.md` の Gate B 記録に残す。該当資料がない場合も **「非該当」と理由**を書き、黙って省略しない。

| 軸 | 値の例 | 意味 |
|----|--------|------|
| **作品経路** | 新規起こし / 資料取り込み / 既存作品の洗練 | 作業の入り口。`資料取り込み` は内容タイプではなく **`source-material-intake`** へ分岐する経路 |
| **作品プロファイル** | 一般 / `mature` / `body_therapy`（**複数可**） | `_how_to`・ユーザスキル・必須構成要素の発動判定 |

## Gate A（骨格ゲート）

合否は **コマンド終了コードを正**とする。許容した WARN がある場合は内容と扱いを Gate B 記録（または完了報告）に残す。

### 新規起こし

1. 既存ファイルと `source_material/` / `_source_material/` の有無を確認する。資料取り込み経路なら本スキルの前に **`source-material-intake`** を優先する。
2. `novel-code-allocate` で採番し、フォルダ名と `config.md` の `novel_ID` を揃える。
3. 必須資料（proposal / design / config / character / world / `_meta.md`）を作成・更新する（中身の厚さは Gate B）。
4. `python tools/novel_scaffold.py novels/<作品>` で `_meta.yaml` と `references/novelai/` 等を揃える。
5. `python tools/novel_character_md_check.py novels/<作品> --profile plan`
6. `python tools/novel_project_check.py novels/<作品>`（不足時は `--bootstrap` 可。character 構造は既定で有効）
7. `config.md` 初回作成時は METRON / CHRONOS を両方 `OFF` とし、Gate B で検査レイヤを使うか確認する。明示的に決めない限り `ON` にしない。
8. METRON / CHRONOS を `ON` にした作品では `python tools/novel_project_check.py novels/<作品> --check-inspection-layers` を追加実行する。保存先不足の WARN は終了コード 0、設定エラーは終了コード 1 とする。

### 既存作品の洗練

1. **再採番しない。** 対象フォルダと `config.md` の整合を `novel_code_allocate.py verify` 等で確認する。
2. 必須資料の有無を確認し、不足・薄いものだけ更新する。
3. character lint と `novel_project_check` を実行する（上記と同じコマンド）。
   既存作品のフラグ行がない場合は `OFF` として扱う。検査レイヤを使うと決めた作品だけ `config.md` の基本情報表へ記録する。

## Gate B（知識ゲート）

Gate A の前後どちらでもよいが、**完了報告の前にすべて満たす。** 手順の詳細正本はこの節。横断の短い完了定義は `concepts.md`。タイトル命名の横断仕様は `workflow-specification.md` の関連仕様を参照する。

### B1. 知識の選択と読込

1. **作品経路・作品プロファイル**を判定し記録する。
2. **`_how_to/_index.md`** を開き、プロファイルに応じた必読だけを選ぶ（**全件必読にしない**）。
3. **`_how_to/skills/_index.md`** の発動条件に当てはまるユーザスキルだけを読む（例: `body_therapy` → `character-body-pick`、mature 系フック → `episode-mature-pick`）。
4. 命名・トロープ・プロフィール候補が必要なら **content-pick-registry** と `python tools/novel_pick_registry.py validate` のあと `pick <list_id>` する（path 直書きは fallback）。
5. 読まなかった必須候補がある場合は **非該当理由**を記録する。

### B2. タイトル命名ゲート

- **新規起こし、またはタイトル変更時**: 候補を **最低 5 件**生成し、比較して 1 件採用する。採用は `proposal.md` / `config.md` の作品名へ反映。不採用 2〜5 件と却下理由は `config.md` の「資料上の別名」へ残す。参照: `_how_to.example/naming.md`、`workflow-specification.md`「タイトル命名ゲート」。
- **既存作品で命名記録がすでにある場合**: 再抽選せず、記録の存在を確認して Gate B 記録に「既存記録を確認」と書く。

### B3. 設計の厚さ

`design_specification.md` について:

1. **初回設計**: 各章に「誰が・何をした・何が変化した」が分かる具体出来事を **5 項目以上**置く。
2. **洗練後**: 各章を原則 **初回項目数の 2 倍**かつ **最低 10 項目**まで増やす。必要に応じて心理の変化も記す。
3. **ストーリー相関図（Mermaid）は必須**。例外は理由を Gate B 記録に残す。
4. **「執筆における必須構成要素」**は、作品プロファイルが `mature` / `body_therapy` 等で該当する場合に必須。非該当なら理由を記録する。

### B4. 洗練パス（必須）

「必要なら」で省略しない。旧 overview の第二パスを固定する。

1. 一度自己評価する（設定・心理・プロットの薄い箇所）。
2. プロット項目を厚くする（B3 の洗練後基準）。
3. 心理描写・具体シーンを増やす。
4. `character.md` のプロフィールを掘り下げる（**novel-character-profile**、必要ならユーザスキル・pick）。

### B5. Gate B 実施記録（`_meta.md`）

`_meta.md` に **Gate B 記録**節を設け（雛形: `_how_to.example/meta.md`）、少なくとも次を残す。

- 作品経路 / 作品プロファイル
- 読んだ `_how_to`（パスまたは索引上の名前）
- 発動したユーザスキル（なければ非該当理由）
- pick の有無（使った場合: `list_id`・seed・採用結果。使わない場合: 非該当理由）
- タイトル命名: 実施 / 既存記録確認 / 例外理由
- 洗練前後の確認（初回章項目数目安 → 洗練後、相関図の有無）
- Gate A で許容した WARN（あれば）

完了報告には、この要約をチャットへ含める。

## Feedback の扱い

既存作品に `judge_result.md` や `impression.md` がある場合は、該当する作家の `writer_profile.md` へ文体・作風の学びとして反映できるかを確認する。

ただし、作品固有の評価本文そのものは作家プロフィールへ丸写しせず、再利用できる傾向・注意点だけを抽出する。

## 関連

- 資料取り込み: `.rulesync/skills/source-material-intake/SKILL.md`
- 採番: `.rulesync/skills/novel-code-allocate/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- 人物プロフィール: `.rulesync/skills/novel-character-profile/SKILL.md`
- 選定レジストリ: `.rulesync/skills/content-pick-registry/SKILL.md`
- 本文保存: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 操作説明: `docs/workflow/planning.md`
- 受け入れ条件: `docs/developer-verification.md`（Plan Mode Gate A / Gate B）
- 任意参照（完了条件ではない）: 説得力の配分は `_how_to.example/episode/general/episode_reality.md`、失敗の許容は `episode_hindrance.md`（作業用があれば `_how_to/episode/general/`）
