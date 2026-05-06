---
targets: ["*"]
description: "Monogatari Coach の横断概念正本"
globs: ["**/*"]
---

# 概念正本

このファイルは、複数のルール・スキル・docs にまたがる概念の短い正本を置く。
長い例、コマンド、provider 別の詳細、トラブルシュートは `docs/` へ置く。

## 正本と副本

定義:
正本は、判断・編集・検証の基準になる一次情報である。副本は、人間の確認、既存バッチ連携、入口生成物、表示用に使う派生情報である。

必須:

- 正本を更新できる状態では、副本だけを直接直して完了扱いしない。
- 副本を直した場合は、対応する正本へ反映してから再生成・再エクスポートする。
- どちらが正本か迷う領域では、作業前に既存ルール・スキルの「正本」節を確認する。

代表例:

| 領域 | 正本 | 副本・派生 |
|------|------|------------|
| ルール・スキル | `.rulesync/rules/`, `.rulesync/skills/` | `AGENTS.md`, `CLAUDE.md` |
| 創作技法雛形 | `_how_to.example/` | `_how_to/` のユーザー調整 |
| 操作説明 | `docs/` | チャット上の要約 |
| 小説本文 | `novels/<作品>/_novel_text/novel_text*.md` | チャット上の本文提示 |
| 書評・興味判定 | `novels/<作品>/_reader/*.md` | チャット上の要約 |
| キャラクタータグ | `novels/<作品>/tag/characters/*.yaml` | `tag/<romaji>.md` |
| 漫画ページ | `novels/<作品>/manga/pages/*.yaml` | `manga/manga_XX.md` |

参照:

- ルール作成規約: `.rulesync/rules/rule-authoring.md`
- 漫画 IR: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- Markdown 互換層: `.rulesync/skills/novel-tag-md-format/SKILL.md`

## 漫画IRと互換Markdown

定義:
漫画ページ・キャラクタータグの編集正本は YAML IR であり、`tag/<romaji>.md` と `manga/manga_XX.md` は YAML から出力する人間向け・既存バッチ向けの互換Markdownである。

必須:

- キャラクタータグの正本は `novels/<作品>/tag/characters/<character_id>.yaml` とする。
- 漫画ページの正本は `novels/<作品>/manga/pages/manga_XX_pYY.yaml` とする。
- 互換Markdownを手で直した場合は、対応する YAML IR へ戻してから再エクスポートする。
- Manga Tag Mode の初手として、`manga/manga_XX.md` だけを直接新規作成して唯一の正本にしない。
- 画像生成前の検証は YAML IR を中心に行い、必要に応じて互換Markdownを生成直前の確認先として使う。

役割:

| ファイル | 役割 |
|----------|------|
| `tools/manga_prompt_ir/schemas/*.py` | 型・必須項目の正本 |
| `tag/characters/*.yaml` | キャラクター外見・衣装・固定タグの編集正本 |
| `manga/pages/*.yaml` | ページ・コマ・人物・セリフ・構図の編集正本 |
| `tag/<romaji>.md` | キャラクタータグの可読副本・既存バッチ互換 |
| `manga/manga_XX.md` | 漫画 Step1 / Step2 の可読副本・既存バッチ互換 |

参照:

- Manga Prompt IR: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- Manga Tag 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`, `docs/image-generation/manga-tag-generation.md`

## Manga Tag Mode の最小ワークフロー

定義:
Manga Tag Mode は、小説本文とキャラクター正本から漫画ページ YAML IR を作り、検証し、必要に応じて互換Markdownや画像生成へ進める作業である。

必須:

1. 本文正本 `novels/<作品>/_novel_text/novel_text*.md` とキャラクター正本を確認する。
2. `manga/pages/*.yaml` を作成・更新する。
3. 主語、関係、行為、セリフ帰属、部分アップの意味、コマ割りを品質ゲートで確認する。
4. `tools/novel_prompt_ir_validate.py` で検証する。本番生成前は `--strict-quality` を推奨する。
5. 互換Markdownが必要なときだけ `tools/novel_prompt_ir_export_md.py` で再エクスポートする。
6. 画像生成は「画像生成: dry-run から本番まで」に従う。

禁止:

- 互換Markdownだけを新規作成・修正して Manga Tag Mode 完了扱いにしない。
- 生成前検証を YAML IR ではなく、互換Markdownだけで済ませない。

参照:

- Manga Prompt IR: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`

## 画像保存先

定義:
生成画像は、作品フォルダ内の用途別ディレクトリに保存し、後から本文・タグ・漫画ページと対応を追える状態にする。

必須:

- キャラクター画像は `novels/<作品>/tag/<romaji>/` に保存する。
- 漫画ページ・コマ画像は `novels/<作品>/manga/_assets/<manga_XX>/` に保存する。
- コマ画像はファイル名接頭辞でページ・コマを区別する。例: `manga_01_p02_k03`。
- ページ単位サブフォルダ（`p01/`, `p02/` など）は既定・推奨にしない。必要な場合だけ任意で使う。

参照:

- 画像レイアウト: `.rulesync/skills/novel-image-layout/SKILL.md`
- 画像生成: `.rulesync/skills/forge-txt2img/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## `_how_to/` と `docs/`

定義:
`_how_to/` は創作技法を扱う準ルール領域であり、`docs/` は人間向けの操作マニュアルである。

必須:

- ツールの操作手順、コマンド例、provider 設定は `docs/` に置く。
- 小説文法、漫画作法、タグ語彙、書評観点は `_how_to.example/` またはユーザー調整領域の `_how_to/` に置く。
- LLM が `_how_to/` を恒久的に更新するのは、ユーザーが明示した場合に限る。

参照:

- docs 記述ルール: `.rulesync/rules/docs-writing.md`
- `_how_to/` の説明: `docs/project-structure/how-to-area.md`

## 画像生成: dry-run から本番まで

定義:
画像生成は、課金・画風・保存先・provider 差異を伴うため、必ず計画確認を挟む。

必須:

1. `.env` と `config/image_generation.json` で provider と設定を確認する。
2. `--dry-run` で provider、モデル、ジョブ数、保存先を確認する。
3. dry-run 結果をユーザーに提示し、明示承認を得る。
4. 承認後にのみ `--dry-run` なしで本番実行する。
5. 本番後、dry-run で示した保存先に画像ファイルが存在することを確認してから完了報告する。

禁止:

- dry-run の提示前に本番実行しない。
- ユーザー承認前に「続けて本番まで」進めない。
- 保存先のファイル確認前に「生成完了」と言わない。

参照:

- 画像生成スキル: `.rulesync/skills/forge-txt2img/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## 画像生成失敗時の provider 切替

定義:
dry-run 承認は、その provider と設定で実行する承認であり、別 provider への自動切替承認ではない。

必須:

- HTTP 429 / 403 / 5xx などで失敗した場合は、provider 名、エラー、対象ジョブまたは範囲を報告する。
- 待つ、provider を変える、範囲を絞るなどの選択肢を提示し、ユーザーの明示指示を待つ。

禁止:

- 別 provider へ自動で切り替えて再実行しない。
- 失敗した provider の承認を、別 provider の本番承認として扱わない。

参照:

- 画像生成スキル: `.rulesync/skills/forge-txt2img/SKILL.md`

## 完了扱い条件

定義:
「完了」は、成果物が正本または保存先に実在し、確認が済んだ状態だけを指す。

執筆:

- 正本 `novels/<作品>/_novel_text/novel_text*.md` に書き込む。
- 書き込み後、再読込または `tools/novel_char_count.py` で確認する。
- 確認後に、更新ファイルパスを添えて完了報告する。
- チャットに本文を出しただけでは完了ではない。

画像生成:

- ユーザー承認後に本番実行する。
- dry-run で示した保存先に画像ファイルが存在することを確認する。
- 確認後に、保存先を添えて完了報告する。

参照:

- 本文出力: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 清書出力: `.rulesync/skills/novel-refinement-output/SKILL.md`
- 画像生成: `.rulesync/skills/forge-txt2img/SKILL.md`

## 評価出力の保存先

定義:
下読み・書評・一般読者の興味判定は、チャット上の感想ではなく、作品フォルダの `_reader/` に保存した評価ファイルを正本とする。

必須:

- First Reader の書評は `novels/<作品>/_reader/YYYYMMDD_HHMM.md` に保存する。
- Interest Check の結果は `novels/<作品>/_reader/interest_YYYYMMDD.md` に保存する。
- チャットには判定、短い理由、改善ポイントの要約だけを返す。
- 書評観点は `_how_to/reader.md`、興味判定のペルソナ・第一印象は `_how_to/standard_reader.md` を参照する。
- 保存したファイルパスをチャットで明示してから完了扱いにする。

禁止:

- チャットに書評本文を出しただけで、評価完了としない。
- `_workingspace/log/` を作品ごとの書評本文の保存先にしない。査証ログには作業事実だけを追記する。

参照:

- 評価出力スキル: `.rulesync/skills/novel-reader-output/SKILL.md`
- 操作説明: `docs/workflow/instruction-driven.md`

## プロジェクト・インテリジェンス

定義:
`_workingspace/` は、作品本文ではなく、プロジェクト横断の計画・履歴・判断理由を管理する領域である。

役割:

| 領域 | 役割 | 正本性 |
|------|------|--------|
| `_workingspace/plans/` | これから行う作業予定、改修順、チェックリスト | 未来・進行中の計画 |
| `_workingspace/log/YYYYMM.md` | そのセッションで何をしたかの作業事実 | 過去作業の査証 |
| `_workingspace/diary/YYYYMM.md` | 次回以降も効く判断理由、好み、運用知見 | 横断ナレッジ |

必須:

- 実施済みの作業事実は査証ログへ追記する。
- 長期的に参照したい判断理由や運用知見は日記へ追記する。
- 作業計画のチェックだけで完了事実の記録を済ませない。
- 査証ログ・日記は既存行を削除、上書き、並べ替えず、追記で更新する。

参照:

- 査証ログ: `.rulesync/skills/workspace-audit-log/SKILL.md`
- 日記: `.rulesync/skills/workspace-diary/SKILL.md`
- 操作説明: `docs/tools/index.md`, `docs/project-structure/index.md`

## 生成モード用語

定義:
画像生成のモード名は、入力粒度と出力の期待値を区別するために使う。

| 用語 | バッチ source | 意味 |
|------|---------------|------|
| コマ生成 | `step1-panels` | 各コマを独立した画像として生成する |
| 精密ページ生成 | `step1-pages` | Step1 相当の具体情報を使い、ページ全体を生成する |
| ページ生成 | `step2-pages` | Step2 相当の抽象化した配置説明で、ページ全体を生成する |
| 背景資料生成 | `background-concepts` | 人物を主役にせず、場所・光・物品配置の参照画像を生成する |

必須:

- コマ生成では、ページ全体のコマ割りタグをそのまま入れない。
- ページ生成・精密ページ生成では、コマ境界、読み順、段、大小が追えるようにする。

参照:

- Manga Tag 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## rulesync

定義:
`rulesync` は、`.rulesync/` 配下の正本を LLM 別入口へ配布する生成・同期レイヤーである。

必須:

- ルールやスキルの主編集先は `.rulesync/` とする。
- `AGENTS.md` / `CLAUDE.md` などの入口ファイルは、原則として生成物・派生先として扱う。
- 入口ファイルへ内容を増やしたい場合は、先に `.rulesync/` 側の正本を更新する。
- `.rulesync/` 更新後、必要に応じて `rulesync generate` を実行し、入口ファイル差分を確認する。

参照:

- ルール作成規約: `.rulesync/rules/rule-authoring.md`
- 導入手順: `readme.md`, `docs/getting-started/index.md`
