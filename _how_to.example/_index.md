# - 創作技法ファイル (how_to/)

葉は **既定では読まない**（この冒頭注記で足りる。行ごとや該当 README に発動条件を足してもよい）。例外として `genre/` の葉は、Plan Mode のジャンル軸が該当すれば必読である（「一からストーリーを出して」のような案出しでも、案を出す前に読む）。Plan Mode は索引からプロファイルに合う葉だけを選び、作品 `_meta.md` の selected に固定する。新しい葉を足すときは、このファイルに入口を1行置き、該当サブカタログに README または `_index.md` があればそこにも置く。作業用 `_how_to/_index.md` がある環境では、そちらへ追随するまで新葉は選定対象外。既存作品の selected は自動では増やさない。手順は `.rulesync/rules/rule-authoring.md`「2.2 創作技法葉の追加」。

0. **（画像参照・横断）** [`image_refs/novelai/README.md`](image_refs/novelai/README.md)
   - NovelAI Vibe / ポーション（`.naiv4vibebundle`）。普段使いは `_how_to/image_refs/novelai/` に置く。作品固有は `novels/<作品>/references/novelai/`。
0. **（創作技法パック）** [`howto_packs/README.md`](howto_packs/README.md)
   - **既定では適用しない。** Gate B で `pack_id` を書いた作品だけ展開する。既存 selected は増やさない。
0. **（ユーザスキル・雛形）** [`skills/_index.md`](skills/_index.md)
   - リポジトリに同梱する**雛形**の一覧。初回はここを **`_how_to/skills/<名前>/` にコピー**してから編集する（正本と副本の扱いは **`.rulesync/rules/concepts.md`**「正本と副本」）。
   - 既にコピー済みの**作業用**一覧は **`_how_to/skills/_index.md`** を正とする（雛形にないスキルが列挙されることもある）。
1. novelcore.md
   - 一般的な小説の文法
3. novel_structure.md
   - 一般的な小説構造のデータベース
3.5. episode/（エピソード技法・雛形）
   - [episode/README.md](episode/README.md) … general（型・職業・対話・設計診断）と common（恋愛・描写・抜粋）の入口。
   - general: [episode/general/episode_.md](episode/general/episode_.md)
   - general（序盤／中盤／終盤／多人数テンポ）: [episode/general/episode_tempo_ensemble.md](episode/general/episode_tempo_ensemble.md)
   - general（展開エンジン／運用カード／勢い展開）: [episode/general/episode_engine_map.md](episode/general/episode_engine_map.md)
   - general（リアリティ）: [episode/general/episode_reality.md](episode/general/episode_reality.md)
   - general（足を引っ張る人物）: [episode/general/episode_hindrance.md](episode/general/episode_hindrance.md)
   - general（地の文モノローグ）: [episode/general/episode_monolog.md](episode/general/episode_monolog.md)
   - general（友人・偽味方・敵対者・危機脱出・恩義・責任移行・部活／サークル・揺らぎ）: [episode/general/episode_friendship.md](episode/general/episode_friendship.md), [episode/general/episode_false_ally.md](episode/general/episode_false_ally.md), [episode/general/episode_antagonist.md](episode/general/episode_antagonist.md), [episode/general/episode_crisis_escape.md](episode/general/episode_crisis_escape.md), [episode/general/episode_obligation.md](episode/general/episode_obligation.md), [episode/general/episode_responsibility_shift.md](episode/general/episode_responsibility_shift.md), [episode/general/episode_club_romcom.md](episode/general/episode_club_romcom.md), [episode/general/episode_circle_romcom.md](episode/general/episode_circle_romcom.md), [episode/general/episode_fluctuation.md](episode/general/episode_fluctuation.md)
   - common: [episode/common/epsode_common.md](episode/common/epsode_common.md)
4. （旧 epsode_common.md は episode/common/ へ移動）
5. rewrite.md, word_change.md
   - 文章校正の時に使う
   - 清書稿は `_novel_text_backup/` に旧版を退避したうえで `_novel_text/` を直接更新する
   - 旧版は `_novel_text_backup/` に **`<元ファイル名>_vNNN.md`** 形式で退避する
   - 清書稿の保存先・バックアップ・`_novel_text` への反映はスキル **novel-refinement-output**（`.rulesync/skills/novel-refinement-output/SKILL.md`）と **`.rulesync/rules/overview.md` §2.5** を参照
6. name_creature.json
   - 人名、クリーチャー名を考えるときの参考にする
   - 人物命名時は、原則としてスキル **character-naming**（`.rulesync/skills/character-naming/SKILL.md`）と **weighted-pick** を併用し、`tools/json_weighted_pick.py` で候補抽出する
6.5. naming.md
   - 小説のタイトル命名、コンセプトに沿った名前の付け方などの技法まとめ
7. world_wear.md
   - 世界の色彩や、人物デザインを考えるときの参考にする
7.5. [`genre/`](genre/README.md)（ジャンル別・横断創作リファレンス）
   - **発動条件**: Plan Mode のジャンル軸（依頼文・`config.md` のジャンル・キーワード）が次のいずれかに該当するとき、その葉を必読とする。該当しないときは読まない。
   - [`genre/inshu_mura.md`](genre/inshu_mura.md) … 因習村・閉鎖的村落。地理、共同体、禁忌、儀礼、排除、秘密、物語構造、配慮。
   - [`genre/isekai_craft.md`](genre/isekai_craft.md) … 異世界クラフト。技術ツリー、スキル制約、社会波及、発明と障害。
   - [`genre/isekai_modern_knowledge.md`](genre/isekai_modern_knowledge.md) … 異世界現代知識無双。知識範囲、解説演出、受容の階梯、実装の壁、考証。
   - [`genre/dungeon.md`](genre/dungeon.md) … ダンジョンもの。迷宮法則、生態系、探索ループ、経済、成長、パーティ、感情設計。
   - [`genre/akuyaku_reijo.md`](genre/akuyaku_reijo.md) … 悪役令嬢。原作知識、破滅回避、人物ロール、断罪、ざまぁ、話法。
   - [`genre/yaminabe_hybrid.md`](genre/yaminabe_hybrid.md) … 闇鍋・多題材混交。出汁（推進軸・計測・不可逆性）、鍋の運用、摩擦設計、品質検定。
8. reader.md
   - 小説の書評・下読みを行うときに使うレビュアープロンプト
   - 評価観点（キャラクター、プロットの完成度、文章力、わかりやすさ、独創性など）と、5段階評価・読後感の期待値・改善サイクルといった出力フォーマットを定義する
   - First Reader Modeの記述を参考にする。ログの出力も必ず行う。
9. standard_reader.md
   - 一般読者の「興味」と「第一印象」を判定するためのプロンプト。ペルソナに基づき、冒頭の掴みや読み飛ばしの有無をシビアに評価する。
9.5. reader_walk.md
   - 一般読者ペルソナが場面ごとに感想と突っ込みを残す。既定は未読の残り全部。作品評価は採点せず、必要時だけペルソナ反応メタデータを記録する。スキル **novel-reader-walk**。
10. tag.md
   - キャラクターごとの画像タグを作成する。新規運用ではスキル **manga-prompt-ir** を優先し、`tag/characters/<character_id>.yaml` を人間編集用の正本、`tag/<romaji>.md` を既存バッチ互換出力として扱う
   - `tag/<romaji>.md` の見出し・**Danbooru Tags** 行の置き方は、Forge 一括生成（`tools/image_provider_novel_tag_batch.py`）と整合させるため、同ファイル内「Markdown ファイル形式（機械抽出と整合）」およびスキル **novel-tag-md-format** を参照
   - 目・髪・肌・種族など**固定特徴が状況ブロック間で抜けなく一貫しているか**は、スキル **novel-tag-character-consistency**（`.rulesync/skills/novel-tag-character-consistency/SKILL.md`）で確認
10.5. character_checklist.yaml, character.md.example
   - `character.md` の必須ラベル・任意ラベル・条件付き子項目を宣言するチェックリスト雛形。運用時は `_how_to/character_checklist.yaml` にコピーして調整する
   - `tools/novel_character_md_check.py` とスキル **novel-character-profile** で参照する
11. （執筆前チェック）スキル **novel-project-readiness** … `tools/novel_project_check.py` で必須資料・`_novel_text` / `_reader` 等を確認（`.rulesync/rules/overview.md` と併用）
11.5. （エピソード抽選）スキル **content-pick-registry**
   - 命名・口調・フック・進行の入口を `list_id` で宣言。
   - **MD 正本 → sync → JSON → registry** の流れで拡充。
   - 一般向け手順雛形: [`skills/episode-general-pick/SKILL.md`](skills/episode-general-pick/SKILL.md)
   - 抽選 CLI: `tools/novel_pick_registry.py`
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
15. physical_assessment.md
   - フィジカルアセスメント・身体観察執筆参照資料（視診・触診・聴診・問診、ケアと観察の二重性、バイタル・スケール目安、描写チェックリスト）。医療・看護・病棟・看病場面を詳細に描く作品で選定する。既定では読まない。
