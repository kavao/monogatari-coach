# Workflow

Monogatari Coach を「どう動かすか」をユーザー視点で把握するためのページです。
まずは **指示文（コピペ）**で進められるページを起点にしてください。

- **最重要**: [指示出しベースのワークフロー](instruction-driven.md)
- **ユーザスキル（プラグイン相当）**: [ユーザスキルと雛形の置き場](user-skills.md) — `_how_to/skills/` に手書きスキルを置くときの正本／雛形／ツールパス（例: カクヨムルビ連携）
- **資料取り込み**: [Source Material Intake](source-material-intake.md)
- **企画・設計**: [Planning](planning.md)
- **評価結果の保存**: [Reader Output](reader-output.md)
- **運用の骨格**: [自己発展型ルールガバナンス](self-evolving-governance.md)

運用上の正本（仕様・詳細）は [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) です。

## ユーザー視点の流れ（何を指示するか）

1. **既存資料があるなら取り込む**
   - `source_material/` や `novels/_import/` を起点に「作品フォルダへ展開して」と指示する
2. **制作の設計（Plan）を固める**
   - `proposal.md` / `design_specification.md` / `character.md` / `world.md` などを作って、と指示する
3. **本文を書く（Writing）**
   - `_novel_text/novel_text*.md` に必ずファイル出力して、と指示する
4. **メタを残す（Meta）**
   - `_meta.md` を更新して進捗と引き継ぎを残して、と指示する
5. **必要になったら派生モードへ**
   - 画像タグ（Tag Mode）や漫画（Manga Tag Mode）を「必要になったタイミングで」指示する
6. **品質を上げる**
   - 清書（文章校正）や下読み（書評）を、保存先ファイルを指定して指示する

## Monogatari Coach の約束（ユーザー視点）

- **本文を会話だけで終わらせません。** Monogatari Coach は必ず `novels/.../_novel_text/novel_text*.md` に保存された状態を正とします。
- **執筆前にプロジェクトの不足がないか確認します。** 可能なら `tools/novel_project_check.py` で機械チェックします。
- **文字数の根拠を統一します。** 文字数は `tools/novel_char_count.py` の結果を正として扱います。
- **成果物の置き場所を混ぜません。** Tag / Manga / Meta は作品フォルダ内で分離して管理します。

## ユーザスキル（プラグイン相当）

公式の `.rulesync/skills/` とは別に、投稿変換や個人用の手順を **`_how_to/skills/<名前>/SKILL.md`** で持てます。雛形は **`_how_to.example/skills/`**、スクリプトは **`_how_to/tools/`** に置くのが既定です。概要・索引・具体例は **[ユーザスキルと雛形の置き場](user-skills.md)** を参照してください。

技術仕様の正本は [`.rulesync/rules/`](../../.rulesync/rules/) と [`.rulesync/skills/`](../../.rulesync/skills/) にあります。
