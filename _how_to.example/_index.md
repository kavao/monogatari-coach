# - 創作技法ファイル (how_to/)
0. **（画像参照・横断）** [`image_refs/novelai/README.md`](image_refs/novelai/README.md)
   - NovelAI Vibe / ポーション（`.naiv4vibebundle`）。普段使いは `_how_to/image_refs/novelai/` に置く。作品固有は `novels/<作品>/references/novelai/`。
0. **（ユーザスキル・雛形）** [`skills/_index.md`](skills/_index.md)
   - リポジトリに同梱する**雛形**の一覧。初回はここを **`_how_to/skills/<名前>/` にコピー**してから編集する（正本と副本の扱いは **`.rulesync/rules/concepts.md`**「正本と副本」）。
   - 既にコピー済みの**作業用**一覧は **`_how_to/skills/_index.md`** を正とする（雛形にないスキルが列挙されることもある）。
1. novelcore.md
   - 一般的な小説の文法
3. novel_structure.md
   - 一般的な小説構造のデータベース
4. epsode_common.md
   - 一般的な小説構造のデータベース、恋愛や親愛要素が多い
5. rewrite.md, word_change.md
   - 文章校正の時に使う
   - 清書稿は `_novel_text_backup/` に旧版を退避したうえで `_novel_text/` を直接更新する
   - 旧版は `_novel_text_backup/` に **`<元ファイル名>_vNNN.md`** 形式で退避する
   - 清書稿の保存先・バックアップ・`_novel_text` への反映はスキル **novel-refinement-output**（`.rulesync/skills/novel-refinement-output/SKILL.md`）と **`.rulesync/rules/overview.md` §2.5** を参照
6. name_creature.json
   - 人名、クリーチャー名を考えるときの参考にする
   - 人物命名時は、原則としてスキル **character-naming**（`.rulesync/skills/character-naming/SKILL.md`）と **weighted-pick** を併用し、`tools/json_weighted_pick.py` で候補抽出する
7. world_wear.md
   - 世界の色彩や、人物デザインを考えるときの参考にする
8. reader.md
   - 小説の書評・下読みを行うときに使うレビュアープロンプト
   - 評価観点（キャラクター、プロットの完成度、文章力、わかりやすさ、独創性など）と、5段階評価・読後感の期待値・改善サイクルといった出力フォーマットを定義する
   - First Reader Modeの記述を参考にする。ログの出力も必ず行う。
9. standard_reader.md
   - 一般読者の「興味」と「第一印象」を判定するためのプロンプト。ペルソナに基づき、冒頭の掴みや読み飛ばしの有無をシビアに評価する。
10. tag.md
   - キャラクターごとの画像タグを作成する。新規運用ではスキル **manga-prompt-ir** を優先し、`tag/characters/<character_id>.yaml` を人間編集用の正本、`tag/<romaji>.md` を既存バッチ互換出力として扱う
   - `tag/<romaji>.md` の見出し・**Danbooru Tags** 行の置き方は、Forge 一括生成（`tools/image_provider_novel_tag_batch.py`）と整合させるため、同ファイル内「Markdown ファイル形式（機械抽出と整合）」およびスキル **novel-tag-md-format** を参照
   - 目・髪・肌・種族など**固定特徴が状況ブロック間で抜けなく一貫しているか**は、スキル **novel-tag-character-consistency**（`.rulesync/skills/novel-tag-character-consistency/SKILL.md`）で確認
10.5. character_checklist.yaml, character.md.example
   - `character.md` の必須ラベル・任意ラベル・条件付き子項目を宣言するチェックリスト雛形。運用時は `_how_to/character_checklist.yaml` にコピーして調整する
   - `tools/novel_character_md_check.py` とスキル **novel-character-profile** で参照する
11. （執筆前チェック）スキル **novel-project-readiness** … `tools/novel_project_check.py` で必須資料・`_novel_text` / `_reader` 等を確認（`.rulesync/rules/overview.md` と併用）
12．manga.md, manga_tag.md, manga_tag_step2.md
   - **manga.md**: 本文から漫画ページIRを起こす手順・YAML構造・**バリアントとタグ注入の優先**（実装と同一の表）・検証の参照先。コマ割りの設計の中心。
   - **manga_tag.md**: コマ・シーン向けの**英語タグ例・語彙**（体勢等）。IRの正本や variant の機械仕様の説明は manga.md に譲る。**Step1／`prompt_tags` 中心**。
   - **manga_tag_step2.md**: **Step2（ページ生成・抽象レイアウト・`step2_summary`）** を編集するときに必ず参照する短いチェックリストと役割分担。雛形は `_how_to.example/manga_tag_step2.md`。
   - 新規運用ではスキル **manga-prompt-ir** を優先し、`manga/pages/manga_XX_pYY.yaml` を正本、`manga/manga_XX.md` を既存バッチ互換出力として扱う
   - 中間データは作り直し可能だが、日本語の意味、人物関係、セリフ帰属、コマの段・大小・読み順は失わない
13. meta.md
   - 小説のメタ情報を管理する。外部投稿用（キャッチコピー、紹介文、タグ）と内部管理用（執筆ステータス、AIへの引き継ぎ指示、伏線管理）の両方を扱う。
   - 執筆の開始時・終了時に参照・更新することで、長期的な執筆の継続性を担保する。
14.（カクヨム向けルビ）雛形 `skills/kakuyomu-convert/`
   - ユーザ作業用に `_how_to/skills/kakuyomu-convert/` へコピーして使う。最短手順は `USER_HINTS.md`（**コピー**／**カクヨムプラグイン**の2点）。`kakuyomu.csv.example` は同梱。実装は `_how_to/tools/kakuyomu_ruby_apply.py`
