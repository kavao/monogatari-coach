---
name: novel-planning
description: >-
  新規作品または既存作品の企画・設計フェーズで、proposal.md、
  design_specification.md、config.md、character.md、world.md、_meta.md などを揃え、
  執筆前確認へつなげる。資料不足時の作成順と確認観点を固定する。
targets: ["*"]
---

## 目的

Plan Mode で、執筆前に必要な Monogatari Coach ファイルを揃え、「迷わず書ける状態」にする。

このスキルは、企画・設計・人物・世界観・メタ情報を整える作業手順を定める。執筆前の機械確認は **`novel-project-readiness`** を併用する。

## 使う場面

- ユーザーが「企画書と設計書を作って」「新しい小説として起こして」などと指示した。
- Source Material Intake 後、展開済み資料を洗練したい。
- 既存作品の `proposal.md` / `design_specification.md` / `character.md` / `world.md` が不足または薄い。

## 作成・確認するもの

| ファイル | 役割 |
|----------|------|
| `proposal.md` | 作品名、ログライン、ターゲット層、あらすじ、キャラクター紹介、魅力 |
| `design_specification.md` | テーマ、コンセプト、章構成、ストーリー相関図、執筆スケジュール |
| `config.md` | novel_ID、writer_code、作品名、作者名、ジャンル、キーワード |
| `character.md` | 登場人物のプロフィール、課題、目的、口調、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術、組織 |
| `_meta.md` | 進捗、伏線、次回タスク、外部投稿用情報 |
| `_meta.yaml` | 画像生成の機械可読設定（現行: NovelAI ポーション）。雛形は `_how_to.example/_meta.yaml.example` |
| `_novel_text/`, `_reader/` | 本文と評価の保存先ディレクトリ |

## 推奨手順

1. 既存ファイルと `source_material/` / `_source_material/` の有無を確認する。
2. 新規作品なら `novel-code-allocate` で採番し、`config.md` とフォルダ名を揃える。
3. **タイトル命名ゲート（必須）**: タイトル候補を最低 5 件生成し、比較して 1 件採用する。
   - **採用**: `proposal.md` の作品名、および `config.md` の「作品名」に反映する。
   - **不採用候補の記録**: `config.md` の「資料上の別名」に候補（2〜5件）と却下理由を残す。
   - 参照（技法の雛形）: `_how_to.example/naming.md`
   - 参照（必須ゲート定義）: `.rulesync/rules/concepts.md`「タイトル命名ゲート（Plan Mode）」
4. `proposal.md` を作り、作品の核を固定する（作品名は上記ゲートで確定済みを前提）。
4. `design_specification.md` を作り、章構成と心理・シーンの流れを具体化する。
5. `character.md` と `world.md` を作り、人物と世界の矛盾を減らす。`character.md` はスキル **novel-character-profile** に従い、`- **ラベル**:` 形式を基本にする。**全キャラに身長（`- **身長**:`）を書く**。
   - **該当条件がある場合のみ** `_how_to/skills/_index.md` を確認し、作品タイプ・チェックリスト・ユーザー指示に応じてユーザスキルを読む（全件必読ではない）。
   - 命名・トロープ・プロフィール候補の抽選は **content-pick-registry** と `tools/novel_pick_registry.py validate` で registry を確認してから `pick <list_id>` する（path 直書きは fallback）。
6. `_meta.md`, `_novel_text/`, `_reader/` を揃える。
7. `python tools/novel_scaffold.py novels/<作品>` で `_meta.yaml` と `references/novelai/` を雛形から作成する（既存の `_meta.yml` は自動で `_meta.yaml` にリネーム）。
8. 必要なら一度自己評価し、設計の薄い部分を洗練する。
9. `python tools/novel_character_md_check.py novels/<作品> --profile plan` で人物プロフィールの構造を確認する。
10. `python tools/novel_project_check.py novels/<作品>` で執筆前の揃いを確認する（不足時は `--bootstrap` でも可）。`character.md` 構造 lint は既定で有効（`plan` profile）。スキップする場合のみ `--no-character-structure`。

## Feedback の扱い

既存作品に `judge_result.md` や `impression.md` がある場合は、該当する作家の `writer_profile.md` へ文体・作風の学びとして反映できるかを確認する。

ただし、作品固有の評価本文そのものは作家プロフィールへ丸写しせず、再利用できる傾向・注意点だけを抽出する。

## 関連

- 資料取り込み: `.rulesync/skills/source-material-intake/SKILL.md`
- 採番: `.rulesync/skills/novel-code-allocate/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- 人物プロフィール: `.rulesync/skills/novel-character-profile/SKILL.md`
- 本文保存: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 操作説明: `docs/workflow/planning.md`
