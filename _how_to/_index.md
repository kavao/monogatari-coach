# - 創作技法ファイル (how_to/)
0. **（画像参照・横断）** [`image_refs/novelai/README.md`](image_refs/novelai/README.md)
   - NovelAI Vibe / ポーション。普段使い: `image_refs/novelai/2026-05-17_flat.naiv4vibebundle`。雛形は `../_how_to.example/image_refs/novelai/README.md`。
0. **（ユーザスキル・手書き運用）** [`skills/_index.md`](skills/_index.md)
   - `.rulesync/skills/` ではない。**試行ワークフロー**などを `_how_to/skills/<名前>/SKILL.md` に置く。一覧は同リンク先。
   - ユーザスキル用の **Python** は **`tools/`（公式）ではなく [`tools/README.md`](tools/README.md) 配下の `_how_to/tools/`** に置く。公式スキルの実装は常にリポジトリ直下の `tools/`。
1. novelcore.md  
   - 一般的な小説の文法
1.5. ethos.md
   - 倫理的な決断、規範の差、忠義と恩義、共同体と個人の衝突を設計するときに選ぶ。標準雛形を参照し、既定では読まない。
2. episode（エピソード技法） … [`episode/README.md`](episode/README.md)
   - **general** [`episode/general/episode_.md`](episode/general/episode_.md)（型・職業・対話・設計診断）／序盤・中盤・終盤・多人数テンポ [`episode/general/episode_tempo_ensemble.md`](episode/general/episode_tempo_ensemble.md)／展開エンジン・運用カード・勢い展開 [`episode/general/episode_engine_map.md`](episode/general/episode_engine_map.md)／リアリティ [`episode/general/episode_reality.md`](episode/general/episode_reality.md)／足を引っ張る人物 [`episode/general/episode_hindrance.md`](episode/general/episode_hindrance.md)／地の文モノローグ [`episode/general/episode_monolog.md`](episode/general/episode_monolog.md)／**common** [`episode/common/epsode_common.md`](episode/common/epsode_common.md)（恋愛・親愛・描写。エピソード案メモは [`epsode_common_ideas.md`](episode/common/epsode_common_ideas.md)、恋愛フック抽選は [`epsode_common_hooks.md`](episode/common/epsode_common_hooks.md)、若妖精の学校・サイズ基準表は [`epsode_common_relations.md`](episode/common/epsode_common_relations.md)）／**mature** [`episode/mature/epsode_mature.md`](episode/mature/epsode_mature.md)（大人向け・ピンクダーク、構文・文章型 [`episode/mature/epsode_mature_syntax.md`](episode/mature/epsode_mature_syntax.md)）。各索引からカテゴリ MD。タスクに応じて必要なファイルだけ読む。
   - **選定レジストリ**: [`pick_registry/`](../_how_to.example/pick_registry/)（雛形）＋ [`pick_registry/`](pick_registry/)（ユーザ）。抽選入口は `python tools/novel_pick_registry.py`（公式 **content-pick-registry**）。
   - **general / common JSON**（フック・進行）: ユーザ MD は [`episode/common/epsode_common_hooks.md`](episode/common/epsode_common_hooks.md) 等。同期は `python tools/episode_general_sync.py --user` / `python tools/episode_common_sync.py --user`。雛形 JSON: [`../_how_to.example/episode/general/episode_general.json`](../_how_to.example/episode/general/episode_general.json)、[`../_how_to.example/episode/common/episode_common.json`](../_how_to.example/episode/common/episode_common.json)。手順雛形: [`../_how_to.example/skills/episode-general-pick/SKILL.md`](../_how_to.example/skills/episode-general-pick/SKILL.md)。
   - **mature JSON**（schema 2.1）: [`episode/mature/episode_mature.json`](episode/mature/episode_mature.json)。list_id は `pick_registry/mature.yaml`（`mature_*`）。MD 更新後は `python _how_to/tools/episode_mature_sync.py`。手順は [`skills/episode-mature-pick/SKILL.md`](skills/episode-mature-pick/SKILL.md)。
   - ピンクダーク: [`pinkdark.md`](pinkdark.md)。ピンクダーク運用時はボディー詳細をプロフィールへ、プロットに治療描写を厚めに。ボディー部位は `tools/json_weighted_pick.py` で候補抽出。
   - `気安い関係`・`話題を考える` の正本は general 側 [`episode_character.md`](episode/general/episode_character.md)／[`episode_dialogue.md`](episode/general/episode_dialogue.md)
3. novel_structure.md
   - 一般的な小説構造のデータベース
4. rewrite.md, [word_change.md](skills/novel-text-rewrite-replace/word_change.md)
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
   - [`genre/inshu_mura.md`](genre/inshu_mura.md) … 因習村・閉鎖的村落。
   - [`genre/isekai_craft.md`](genre/isekai_craft.md) … 異世界クラフト・ものづくり・辺境開拓。
   - [`genre/isekai_modern_knowledge.md`](genre/isekai_modern_knowledge.md) … 異世界現代知識無双・知識チート・内政再建・異世界探偵。
   - [`genre/dungeon.md`](genre/dungeon.md) … ダンジョン探索・迷宮都市・現代ダンジョン・デスゲームVR・迷宮運営。
   - [`genre/akuyaku_reijo.md`](genre/akuyaku_reijo.md) … 悪役令嬢・乙女ゲーム転生・破滅回避・断罪。
   - 各ユーザー運用ファイルから [`../_how_to.example/genre/`](../_how_to.example/genre/README.md) の基準本文を参照し、複数作品へ共通するローカル調整だけを記録する。
8. reader.md
   - 小説の書評・下読みを行うときに使うレビュアープロンプト
   - **6項目100点満点**（冒頭の牽引力/キャラクター/プロット期待値/文章力/わかりやすさ/独創性）。閾値 70 / 55–69 / 54。**G1冒頭/G2章完/G3全文**の段階ゲートあり。
   - ログの出力も必ず行う（スキル **novel-reader-output**）。
8.5. editor_score.md（`_how_to.example/editor_score.md` 参照・必要ならコピー）
   - 足切り（reader.md）通過後の**深掘り採点**。5項目100点（構造/キャラ/文体/世界観/完成度）。致命的弱点の優先順位出しが目的。スキル **novel-evaluation-output**。
8.6. novel_synopsis_for_review.md（`_how_to.example/novel_synopsis_for_review.md` 参照・必要ならコピー）
   - G3全文評価・Editor Score の前処理として使う客観的あらすじ（400字前後）。長文30,000字超の場合に推奨。
8.7. consistency_audit.md（`_how_to.example/consistency_audit.md` 参照・必要ならコピー）
   - 複数章完成後の**設定・口調・時系列の一貫性監査**（表形式）。スキル **novel-evaluation-output**。
9. standard_reader.md
   - 一般読者の「興味」と「第一印象」を判定するためのプロンプト。ペルソナに基づき、冒頭の掴みや読み飛ばしの有無をシビアに評価する。
9.5. reader_walk.md
   - 一般読者ペルソナが場面ごとに感想と突っ込みだけを残す。既定は未読の残り全部。採点しない。スキル **novel-reader-walk**。雛形: `_how_to.example/reader_walk.md`。
10. tag.md
   - キャラクターごとの画像タグを作成する。新規運用ではスキル **manga-prompt-ir** を優先し、`tag/characters/<character_id>.yaml` を人間編集用の正本、`tag/<romaji>.md` を既存バッチ互換出力として扱う
   - `tag/<romaji>.md` の見出し・**Danbooru Tags** 行の置き方は、Forge 一括生成（`tools/forge_novel_tag_batch.py`）と整合させるため、同ファイル内「Markdown ファイル形式（機械抽出と整合）」およびスキル **novel-tag-md-format** を参照
   - 目・髪・肌・種族など**固定特徴が状況ブロック間で抜けなく一貫しているか**は、スキル **novel-tag-character-consistency**（`.rulesync/skills/novel-tag-character-consistency/SKILL.md`）で確認
10.5. character_checklist.yaml（未コピー時は `../_how_to.example/character_checklist.yaml`）
   - `character.md` の必須ラベル・任意ラベル・条件付き子項目を宣言するチェックリスト。必要に応じて `_how_to/character_checklist.yaml` にコピーして調整する
   - `tools/novel_character_md_check.py` とスキル **novel-character-profile** で参照する
11. （執筆前チェック）スキル **novel-project-readiness** … `tools/novel_project_check.py` で必須資料・`_novel_text` / `_reader` 等を確認（`.rulesync/rules/overview.md` と併用）
12．manga.md, manga_tag.md, manga_tag_step2.md
   - **tag.md**（雛形: `../_how_to.example/tag.md`）: キャラ Tag Mode。**0 番 `00_base`（固定特徴のみ）**＋状況バリアント。未コピーなら example を参照。
   - **manga.md**: 本文から漫画ページIRを起こす手順。**TPO→variant 表を `_meta.md` で先に固定してから YAML**・バリアントとタグ注入の優先・検証の参照先。コマ割りの設計の中心。
   - **manga_tag.md**: コマ・シーン向けの**英語タグ例・語彙**（体勢・nsfw等）。IRの正本や variant の機械仕様の説明は manga.md に譲る。**Step1／`prompt_tags` 中心**。
   - **manga_tag_step2.md**: **Step2（ページ生成・抽象レイアウト）** 用。未編集なら `../_how_to.example/manga_tag_step2.md` を参照。作品固有ルールは `_how_to/manga_tag_step2.md` に追記。
   - 新規運用ではスキル **manga-prompt-ir** を優先し、`manga/pages/manga_XX_pYY.yaml` を正本、`manga/manga_XX.md` を既存バッチ互換出力として扱う
   - 中間データは作り直し可能だが、日本語の意味、人物関係、セリフ帰属、コマの段・大小・読み順は失わない
13. meta.md
   - 小説のメタ情報を管理する。外部投稿用（キャッチコピー、紹介文、タグ）と内部管理用（執筆ステータス、AIへの引き継ぎ指示、伏線管理）の両方を扱う。
   - **§3.1 表紙**: 題字方針（`組版` / `logo_asset` / `後回し`）と題字ロゴ状態。雛形は [`publishing/`](publishing/)。
   - **§4 漫画 variant 対応（TPO 正本）**: Manga Tag 前に区間ごとの状況バリアントを表で固定（詳細は `manga.md`）。
   - **§7 出版パッケージ進捗**: book / cover / lock / reader-proof の完成目安表。
   - 執筆の開始時・終了時に参照・更新することで、長期的な執筆の継続性を担保する。
13.5. publishing/（表紙合成・題字ロゴ雛形）
   - [`publishing/title_logo_plan.md`](publishing/title_logo_plan.md)／[`title_logo_order.yaml.example`](publishing/title_logo_order.yaml.example)／[`cover.yaml.example`](publishing/cover.yaml.example)／[`cover_assets_README.md`](publishing/cover_assets_README.md)
   - 正本雛形は `_how_to.example/publishing/`。操作は `docs/workflow/cover-composition.md`。
14. （カクヨム向けルビ）[`skills/kakuyomu-convert/SKILL.md`](skills/kakuyomu-convert/SKILL.md)
   - 一覧・入口は項0の [`skills/_index.md`](skills/_index.md)。作品フォルダに `kakuyomu.csv` を置き、実装は **`_how_to/tools/kakuyomu_ruby_apply.py`**。最短手順は **`_how_to.example/skills/kakuyomu-convert/USER_HINTS.md`**（**コピー**／**カクヨムプラグイン**）。雛形フォルダを `skills/kakuyomu-convert/` にコピー済みなら、その直下の `USER_HINTS.md` でよい。雛形の置き換え・リセット時は **`_how_to.example/skills/kakuyomu-convert/`** を参照。
