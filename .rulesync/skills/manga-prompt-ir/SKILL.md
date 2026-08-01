---
name: manga-prompt-ir
description: >-
  漫画ページ・漫画コマ・キャラクター定義を YAML/JSON/Pydantic の中間表現で管理し、
  画像生成向けの自然文プロンプト、タグ列、テキスト要素へ変換する。
targets: ["*"]
---

# Manga Prompt IR

> 横断正本: YAML IR と互換 Markdown の正本・副本関係は **`.rulesync/rules/workflow-specification.md`** の「漫画IRと互換Markdown」を正とする。このスキルは、Manga Prompt IR を実際に編集・検証・エクスポートするときの作業手順を扱う。

## 目的

キャラクタータグと漫画タグを、**単なる Markdown 抽出だけに依存せず**、Pydantic モデル・YAML・JSON・互換 Markdown の役割を分けて管理する。正本と副本の横断定義は `concepts.md` に置き、本スキルではその IR をどう作り、検証し、画像生成向けへ変換するかを定める。

このスキルは、次の3つを分離して管理する。

- **キャラクター定義**: 外見・衣装・性格・固定タグ・禁止変更項目
- **漫画ページ定義**: ページ単位のレイアウト、コマ、人物、セリフ、効果音
- **背景概念定義**: ページや章で使う人物なしの背景・空間設計
- **レンダリング**: 画像生成モデルごとの自然文プロンプト、タグ列、テキスト要素抽出

## 正本の優先順位

1. `tools/manga_prompt_ir/schemas/*.py`: Pydantic v2 モデル。構造・必須項目・型の正本。
2. `tools/manga_prompt_ir/examples/*.yaml`: 人間が編集する入力例。作品ごとの YAML はこの形に寄せる。
3. `tools/manga_prompt_ir/converters/*.py`: YAML/JSON を読み、モデル検証後にプロンプトへ変換する参考実装。
4. `tag/<romaji>.md` / `manga/manga_XX.md`: 既存ツール互換・**人間向けの可読副本**・旧資産からの移行元として扱う。

正本・副本関係の詳細は **`.rulesync/rules/workflow-specification.md`** の「漫画IRと互換Markdown」を参照する。

## ユーザー向けマニュアル（ツール・パイプライン）

創作技法は `_how_to/manga.md` に置き、**コマンド・検証・バッチ・ネガ合成・export フラグ**など運用手順は `docs/` に分離している。

- **`docs/image-generation/manga-prompt-ir.md`**: `novel_prompt_ir_validate.py` / `novel_prompt_ir_embed_snapshots.py` / `novel_prompt_ir_export_md.py`（`--novelai-pipe-tags` 等）、`image_provider_novel_manga_batch.py` の `--source`、コマ単位ネガの合成順。
- **`docs/image-generation/manga-tag-generation.md`**: 互換 `manga/manga_XX.md` の Step1/Step2 長文テンプレ・実例・レイアウト記述・生成モード別の運用メモ。

## 運用方針

- このIRは、生成途中で壊れたら作り直せる **再生成可能な中間データ**として扱う。正本性の中心は、YAML形式そのものではなく、そこに入っている **日本語の意味・人物関係・場面意図・セリフ帰属**に置く。
- 小説本文からの変換を主体にする場合、最初のIRは荒くてもよい。品質ゲートで意味を補い、必要ならIR全体を再出力する。
- 新規のキャラクタータグは、まず `character.yaml` 相当の構造へ落とす。
- 新規の漫画タグは、まず `manga_page.yaml` 相当の構造へ落とす。

## Manga Tag の入口（variant・タグ層は YAML より先に `_meta` で固定）

ページ YAML を書く前に、作品 **`_meta.md`** で次を**別表**で合意する。

1. **「漫画 variant 対応（TPO 正本）」** — 区間ごとの **状況バリアント（`01_` 以降）** → YAML は `subjects[].variant_id`
2. **「漫画タグ層（区間・常時上乗せ）」** — 区間ごとに全コマへ足す／外す **英語タグ** → YAML は区間内各ページの `render_instruction.user_directives.defaults`（バッチは `_meta` を直接読まない）。§5 テーブルから YAML への転記漏れを防ぐには `python tools/novel_manga_apply_tag_defaults.py novels/<作品> [--apply]` を使う。

表の書き方・3層（variant / タグ層 / コマ固有）の分担は **`_how_to.example/meta.md`** §4・§5 と **`_how_to.example/manga.md`** の「TPO → variant 対応表」を正とする。横断ワークフローの必須順は **`.rulesync/rules/workflow-specification.md`** の「Manga Tag Mode ワークフロー」。
- `character_id` はキャラクター一貫性の主キーとし、ページ側の `character_ids` と各コマの `subjects[].character_id` から参照する。
- セリフ、モノローグ、ナレーション、効果音は混ぜず、`text.dialogue` / `text.monologue` / `text.narration` / `text.sfx` に分ける。
- 漫画ページ YAML を単体で画像モデルへ渡す運用では、`render_instruction` に作画依頼文を入れる。外側の Markdown やチャット冒頭文が無くても、何を描くか・コマ割りをどう扱うか・キャラクター外見をどう継承するかが読める状態を正とする。
- 画像生成モデルが文字描画を苦手とする場合に備え、テキスト要素は `extract_text_elements()` で別処理できる形にする。
- `negative_tags` はキャラクター側とページ側の両方に持たせ、最終レンダリング時に結合する。
- **コマ単位 txt2img**（`image_provider_novel_manga_batch.py`・`--source step1-panels`）では、
  各コマのネガを **`--negative-prompt` + `technical.negative_tags` + `panels[].negative_tags`** として合成し、
  **`panels[].omit_negative_tags`** に書いた断片（例: `split screen`）を共通ネガから除いてからコマ別ネガを足す。
  スキーマは `tools/manga_prompt_ir/schemas/manga_page.py` の `Panel.negative_tags` / `Panel.omit_negative_tags`。
  provider 別 formatter は `tools/manga_prompt_ir/prompt_formatters.py` で解決する。NovelAI は既定で
  `novelai_pipe`（`ベース | キャラ` + native negative）、Forge は `tag_csv`、Grok / OpenAI / OpenRouter 系は
  `natural_sections`（コマ文脈・人物・構図・照明・タグヒント・`Do not include`）を使う。
- **ページ単位生成**（`image_provider_novel_manga_batch.py`・`--source step1-pages` / `--source step2-pages`）では、
  既存の `yaml_page_step1_text()` / `yaml_page_step2_text()` で組み立てたページ指示文を素材として、
  `tools/manga_prompt_ir/prompt_formatters.py` の `manga_page_instruction` へ通す。Grok / OpenAI / OpenRouter 系では
  `--negative-prompt` と `technical.negative_tags` を prompt 内の **`Do not include`** へ移し、API に渡す
  `negative_prompt` は空にする。旧来形式との比較は `--prompt-formatter tag_csv` で行える。
- 漫画固有タグ（画風・レイアウト・トーン）とキャラクター固有タグ（髪・目・衣装・種族・固定小物）は分けて保持する。
- コマ・ページ画像（`step1-panels` / `step1-pages` / `step2-pages`）の保存先は `manga/_assets/<manga_XX>/comic/`。
- 背景・空間・反復オブジェクトの参照資料は **`background_concepts[]`** に書く（詳細は下記「`background_concepts[]`（Manga Tag Mode）」）。`--source background-concepts` で人物なしの背景資料画像を生成する。標準 provider は `grok`。保存先は `manga/_assets/<manga_XX>/backgrounds/`。
- **`scene` の日本語と英語**: `location` / `time_of_day` / `weather` / `background_notes` は人間向けに日本語でもよい。**タグ行・バッチは `location_en` / `time_of_day_en` / `weather_en` / `background_notes_en` のみ**を `tools/manga_prompt_ir/scene_prompt.py` が参照し、日本語キーには**フォールバックしない**。**`location_en` は必須（非空）**。`background_notes`・`time_of_day`・`weather` を書いたときは対応する `*_en` も必須（欠けると `MangaPagePrompt`／`Scene` の検証エラー）。LLM 側で英語行を埋めてから保存する運用を正とする。
- **`subjects[]` の背景・オブジェクト（`character_id` なし）**: `description` は日本語のままでよい。タグ行は **`description_en`** または **`tag_token`** があればそれを使う。**どちらも無く**、`description` が日本語（CJK を含む）のみのときはタグ上は **`subject`** プレースホルダとなり、日本語をタグ列に載せない（`subject_tag_line_token()`）。英語のみの `description` は後方互換でタグに載りうる。
- **`composition` / `camera` / `lighting` とコマの状況語（タグ行）**: Step1 の機械連結タグ（`image_provider_novel_manga_batch`・`novel_prompt_ir_export_md`）では **`framing_en` / `focus_en` / `perspective_en` / `layout_en`**、**`camera` の `*_en`**、**`lighting` の `*_en`**、**`pose_action_en` / `expression_en`** を優先する。旧キー（`focus` 等）は **CJK を含まないときだけ**タグに載せる（`medium shot` のような英語のみは従来 YAML でも可）。**`panels[].mood_atmosphere_en`** があればタグに使い、無い場合は `mood_atmosphere` のうち CJK を含まない要素のみ。実装の中心は **`tools/manga_prompt_ir/scene_prompt.py`**。
- **`focus_en` はキャラ ID 単体を書かない**（例: `yuna` / `hayate` は不可）。構図・注視点は **Danbooru 風の英語タグまたは短い英語フレーズ**（例: `glowing phone screen`, `lying figure on bed`, `hayate's eyes`）とし、固有名・外見固定は **`subjects[]` と NovelAI パイプのキャラ列**に任せる。
- **人名トークンの機械除外（tag_csv / NovelAI pipe base）**: `yaml_panel_tags`（挿絵バッチ・Forge 等の **tag_csv**）および `yaml_panel_tags_novelai_split` の **ベース列**では、タグ全体が当該ページの `character_id` / `name_en` / `name`（正規化後）と一致するとき除外する（`tools/manga_prompt_ir/character_token_filter.py`）。`yaml_panel_tags` は **`name_en` 等を subjects から後付けしない**。フレーズ（`summary_en` や `glowing phone screen`）は残る。NovelAI pipe の **キャラセグメント先頭の `name_en`** はパイプ識別用として残す（tag_csv スコープ外）。

### キャラクターIR・外見初版を新規に起こすとき（`world_wear.md`）

**対象**: `novels/<作品>/tag/characters/<character_id>.yaml` を**新規作成**するとき、または `novels/<作品>/character.md` に**外見・服装の初版**を書き起こすとき（該当キャラの構造化タグ正本がまだ無い／外見が未確定の段階）。**舞台のトーン・配色・服の文化感**を決める前の参照として使う。

**必須動作**（エージェント／人間）:

1. **`_how_to/world_wear.md` を開いて参照する**（ユーザーが `_how_to/` に独自版を置いている場合はそちらを優先。リポジトリ同梱の雛形・索引は **`_how_to.example/world_wear.md`**・**`_how_to.example/_index.md`**）。
2. 得た目安を **`character.md`**、および **`tag/characters/<character_id>.yaml`**（`costume`・`prompt_variants[].danbooru_tags` 等）へ反映する。衣装の**色相**は `white_shirt` のように **Danbooru 系トークンで明示**する運用を推奨（詳細は **`_how_to.example/tag.md`** の衣装・固定タグの節）。

**対象外**（この節を満たさなくてよい）:

- 既存キャラ YAML への**軽微な修正のみ**、**`manga/pages/*.yaml` だけ**の改稿など、**外見正本の新規起こしを伴わない**作業。
- 作品設定が `world_wear` の想定と合わない場合は**当てはまる節だけ**読むか、**参照を省略**してよい（必要なら作品の **`_meta.md`** に「未参照・理由」を一言メモする運用可）。

**備考**: `world_wear.md` はツールが自動では読み込まない創作技法ファイルである。本節は **Tag Mode の初回・キャラ初版づくり**に効き、既存IRの細かな差し替えだけのセッションでは負荷をかけないための区別を置いた。

## `background_concepts[]`（Manga Tag Mode）

**Manga Tag Mode でページ YAML を新規作成・改稿するとき**、コマの `panels[]` だけで終えず、**同じファイルに `background_concepts[]` を必ず検討して記載する**。空のまま（未記載・`[]` のみ）でタグ作成完了とみなさない。

### 件数とタイミング

- **原則: 1ページあたり最低1件**。複数コマ・複数視点があるページは **2件以上** もよい。
- **シーン・場所・章の最初のページ**（舞台が変わる・読者に空間を見せる導入）では、**establishing / wide** 系の空間概念を **必ず1件以上** 入れる（`concept_id` に `establishing`・`wide` などの視点語を含めると追跡しやすい）。
- 直前ページと **同一舞台・同一光・同一小道具配置** で差がない場合のみ、当該ページを省略してよい。そのときは作品 `_meta.md` または `render_instruction.user_directives.page_notes` に **「背景は前ページ pYY の ○○ を再利用」** と一言残す。

### 「背景」だけではない（オブジェクト・UI も含む）

`background_concepts[]` は **室内・外景の空間設計** に加え、ページ内で繰り返し効く **オブジェクト／UI／小道具** の参照資料も載せる。

- 例: 執筆アプリのグレーUI、実験机とキーボード、窓からの五月の空、モニタ光だけの画面プレート
- コマの `subjects[]` で `type: object`（または `character_id` なしの重要物）があるとき、**ページを通じて一貫させたいもの**は、コマタグだけに頼らず **背景概念としても切り出す**のが正しい運用
- 各要素は **人物を主役にしない**英語 `prompt`（`description` は日本語可）と、`negative_tags`（`people`, `chimpanzee`, `1boy` 等）で **背景資料生成**（`background-concepts`）向けに書く

### フィールドと生成

- 型の正本: `tools/manga_prompt_ir/schemas/manga_page.py` の `BackgroundConcept`
- 必須: `concept_id`, `title`, `description`, `prompt`（例は `tools/manga_prompt_ir/examples/manga_page.yaml`）
- 画像生成: `image_provider_novel_manga_batch.py --source background-concepts`（`--mode` 別名可）。品質点検はスキル **`manga-tag-quality-gate`** の「背景概念」節

## `panels[].summary_en`（コマ要約の英訳）と NovelAI タグ併用

横断正本は **`.rulesync/rules/workflow-specification.md`** の「Manga `summary_en` の翻訳経路」。

### 主経路（エージェント＋検証）

- **`summary`（日本語）を書いた同ターンで**、`summary_en`（英語1文）と **`summary_en_source`（= そのときの `summary` 原文）** を YAML に書く。`location_en` / `pose_action_en` と同型の運用。
- エージェント向けルール:
  - キャラ名はローマ字（`ren`, `tsubomi` 等）。`summary_en` に CJK を含めない。
  - タグ併用を想定し **1文・パイプ `|` なし・概ね 220 文字以内**（`tools/manga_prompt_ir/summary_en.py` の `sanitize_summary_en_for_tags` と整合）。
  - `summary` のみ直したら **`summary_en` も更新**する（`summary_en_source` 不一致は validate が検出）。
- **完了判定**: `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` の **exit 0**（チャットだけで翻訳完了とみなさない。YAML 書き込み後に実行・確認）。
- **NovelAI `step1-panels`**: `summary_en` は **`prompt_tags` と同じプロンプトのベース側**に併用（既定 ON。`--no-include-panel-summary` で無効化）。
- 品質ゲート（スキル **`manga-tag-quality-gate`** と併用）: 全コマで `summary` / `summary_en` ペア、`summary_en` に CJK なし。

### 任意経路（翻訳ツール・一括再翻訳）

- `python tools/novel_manga_panel_summary_en.py novels/<作品>` — エージェントなしで YAML だけ直したとき、または一括再翻訳。`.env` の `MONOCRI_SUMMARY_EN_PROVIDER`（`openrouter` 可）と対応 API キーが必要。**主経路の代替ではなく、従経路**。
- 実行後も `novel_prompt_ir_validate.py --strict-quality` で確認する。

### 禁止・注意

- **エディタでの漫然たる英語入力**（`summary_en_source` なし・validate 未確認）で完了扱いにしない。
- `OPENAI_API_KEY` 未設定は **翻訳ツール未実行の理由にはなるが、主経路（エージェント翻訳）のブロッカーではない**。

## `_how_to/manga_tag.md` との役割分担（漫画タグ・語彙・置き換え）

**創作技法としてのコマ割り・ページ設計・IR の組み立て**は **`_how_to/manga.md`**（雛形は `_how_to.example/manga.md`）。構造・型・正本/副本の横断定義は **`.rulesync/rules/concepts.md`** と本スキル、検証の実装は `novel_prompt_ir_validate.py` が担う。**ツール連携の手順の詳細**は **`docs/image-generation/manga-prompt-ir.md`**、**互換 Markdown の Step1/Step2 長文テンプレ・実例**は **`docs/image-generation/manga-tag-generation.md`**。一方、**コマ単位の英語タグ語彙・置き換え・NSFW 表記の慣例**は **`_how_to/manga_tag.md`**（雛形は `_how_to.example/manga_tag.md`）を正とする。**Step2 要約・抽象ページ指示**は **`_how_to/manga_tag_step2.md`**（雛形 **`_how_to.example/manga_tag_step2.md`**）を正とする。

### エージェント／人間の必須動作（ページ YAML を新規・改稿するとき）

1. **`manga/pages/*.yaml` の `panels[].prompt_tags` を書く前に**、必ず **`_how_to/manga_tag.md`** を読む（ユーザーが `_how_to/` をカスタムしている場合はそちらが優先。未編集なら `_how_to.example/manga_tag.md` と同内容を想定）。
1b. **`panels[].step2_summary` を詰める・互換 Markdown の `### Step2` を人間が整える**ときは、**`_how_to/manga_tag_step2.md`**（雛形は `_how_to.example/manga_tag_step2.md`）を**必ず**開く。Step1 の語彙表だけでは足りない（抽象レイアウト・言い換えの作法）。
2. 次を **`prompt_tags` に反映する**（ファイルに書いたルールを機械が自動検証するわけではないため、**人手で反映するまで完了とみなさない**）。
   - **置き換えリスト**: 作品内隠語・言い換えを、 `manga_tag.md` の表に合わせる。
   - **追加ルール**: 該当コマでは `manga_tag.md` の追加ルールに従う。
   - **視点**: `male perspective`, `pov` など、ファイルで推奨されている表記に寄せる。
   - **カラー指向時・ページの `manga` 節**: **原則 `monochrome` と `screentone` を `manga.genre_tags` / `manga.visual_tags` に入れない**（`novel_prompt_ir_export_md.py` が各コマの互換 Step1 `tag` 行へ連結する）。コマの `prompt_tags` だけでなく YAML の **`manga`** を **`_how_to/manga.md`**（雛形 `_how_to.example/manga.md`）の「`manga.genre_tags` / `manga.visual_tags`」節に合わせる。**意図的にモノクロ作品にする場合のみ**例外。コマ単位では従来どおり **`manga_tag.md`** の `screentone` 除外など運用上の禁止・除外も参照。
   - **色モード正本**: ページYAMLの **`color_palette.mode`** をページ単位の色モード正本とする。値は `monochrome` / `limited_color` / `full_color`。`manga.visual_tags` は補助タグとして併用するが、`mode=monochrome` に `full_color` 系タグ、`mode=full_color` に `monochrome` / `screentone` 系タグがある場合は `novel_prompt_ir_validate.py` が **WARNING** を出す。センターカラー・巻頭カラー・扉絵だけカラー・一部限定色などの意図的例外を想定し、通常運用では自動修正・通常エラー化しない。
   - **背景のみ**: `nohuman` 等、ファイルで定義されているルール。
3. **`manga.md` / `manga_tag.md` / `manga_tag_step2.md` / `docs/` を混同しない**: `manga.md` は創作技法としての組み立て；**コマ英語タグの語彙は `manga_tag.md`（Step1 中心）**；**Step2 要約・抽象ページ指示は `manga_tag_step2.md`**；**バッチ・export のコマンド体系は `docs/image-generation/manga-prompt-ir.md`**。`prompt_tags` なら **`manga_tag.md`、Step2 文面なら `manga_tag_step2.md` を開いたか**を確認する。

### ツール側の限界（期待値の調整）

- `novel_prompt_ir_validate.py` は **Pydantic 型・参照・品質ゲート**を検証するが、**`manga_tag.md` の置き換え表どおりかまでは検証しない**。
- 置き換えの自動適用をコードに足す場合は **`tools/`** に実装し、本スキルからパスを参照する（スキルディレクトリに Python を置かない）。

## ユーザ指示の正本（`render_instruction.user_directives`）と prompt_tags の強制適用

漫画ページIRに対するユーザ指示（品質修正の軸・必ず効かせたいタグ運用）を、
**ページ単位で構造化された正本**として保持する。狙いは、生成→評価→修正の
ループで指示がぶれないようにし、**Markdown 互換出力（Step1）と画像生成バッチ
（NovelAI 分割含む）に同じ強制を効かせる**こと。

### 置き場と意味

- ページ単位（**正本**）: `render_instruction.user_directives`
  - `page_notes: list[str]`: 自然文のユーザ指示。何を直したいか・譲らない方針を残す。
  - `defaults`:
    - `required_prompt_tags: list[str]`: そのページの全コマに**必ず追加**する `prompt_tags`。
    - `omit_prompt_tags: list[str]`: そのページの全コマから**必ず除外**する `prompt_tags`。
- コマ単位（**上書き**）: `panels[]`
  - `required_prompt_tags: list[str]`: そのコマに必ず追加する `prompt_tags`。
  - `omit_prompt_tags: list[str]`: そのコマから必ず除外する `prompt_tags`。

対象は **ポジ側 `prompt_tags` のみ**。negative 側は既存の
`Panel.negative_tags` / `Panel.omit_negative_tags` と CLI 共通ネガで扱う。

### 適用順（ツール実装と一致）

1. 既存の `panels[].prompt_tags`（および scene/composition 等から組み立てた状況タグ）を収集。
2. `defaults.required_prompt_tags` → `panels[].required_prompt_tags` の順で**末尾に加算**。
3. `defaults.omit_prompt_tags` ∪ `panels[].omit_prompt_tags` を**最後に除外**。
4. 重複除去のうえタグ列を確定。

実装は `tools/manga_prompt_ir/user_directives.py` に共通化されており、
`tools/image_provider_novel_manga_batch.py`（YAML入力の Step1 系）と
`tools/novel_prompt_ir_export_md.py`（Step1 互換タグ行）が同じ関数で適用する。
NovelAI 分割（`base | キャラ`）では **`required` は base 側のみへ加算**し、
**`omit` は base / キャラセグメントの両方から除外**する。

### 運用（ぶれないための手順）

- ユーザ指示は**まず `render_instruction.user_directives.page_notes` に残す**。
  チャットの文章だけで指示を保持しない（次のセッションで失われる）。
- 全コマへ波及させたい「必ず追加／必ず除外」は `defaults` に書く。
  例外コマだけ `panels[].required_prompt_tags` / `omit_prompt_tags` で上書きする。
- `panels[].prompt_tags` に書くのは「そのコマ固有の演出タグ」。
  全コマへ効かせたい指示を毎コマの `prompt_tags` に二重記載しない。
- 修正のループに入る前に
  `python tools/novel_prompt_ir_validate.py novels/<作品>` を回し、
  下記の警告が出ていないかを必ず確認する。本番生成前は `--strict-quality`。

### `novel_prompt_ir_validate.py` の検出（警告）

- `defaults` の `required_prompt_tags` と `omit_prompt_tags` に同じタグがある。
- `panels[].required_prompt_tags` と `panels[].omit_prompt_tags` に同じタグがある。
- `panels[].required_prompt_tags` がページ既定の `omit_prompt_tags` と衝突する。
- `panels[].omit_prompt_tags` がページ既定の `required_prompt_tags` と衝突する。
- `panels[].prompt_tags` に `omit_prompt_tags` 対象タグが残っている（生成時に
  自動除去されるが、指示の二重記載を示すサイン）。

これらは矛盾そのものをエラーにせず、**改稿の指針**として警告で出す。
本番直前の `--strict-quality` ランで失敗扱いにすれば、矛盾を残したまま
画像生成へ進むことを防げる。

### ドキュメント側の用例

`docs/` には **強制追加／強制削除のコピペ用例**を置く。スキル（本ファイル）は運用方針と正本の所在を定め、具体例は操作マニュアルへ寄せて更新する。

- 用例: [`docs/image-generation/manga-prompt-ir.md`](../../../docs/image-generation/manga-prompt-ir.md) の「ユーザ指示の正本（強制追加・強制削除）」

## prompt_variants の `variant_id` と見出し番号（ツールの実際の動き）

キャラクター YAML の `prompt_variants[].variant_id` について、スキーマ・ツールは次のように振る舞う。

- **Pydantic 上の型**: `variant_id` は **任意の文字列**。推奨形式 **`NNN_short_slug`（3桁ゼロ埋め）** は **スキーマでは強制されない**。英字のみの ID（例: `normal`）でも検証は通る。
- **命名・階層の正本**: **`.rulesync/rules/workflow-specification.md`**（「Tag Mode バリアント階層」「Tag Mode 身体的正本（3階層継承）」「Tag Mode 汎用テンプレートとカスタム要素」）。標準成果物は **`000_base` → 000番台（着衣）→ `006_nude`（NSFW 作品）→ 100番台（資料、`combines_with` 付き）**。100番台を省略するときは省略理由を残す。
- **テンプレート一式**: チャットまたは作品 `_meta.md` の**バリアント方針**が **`テンプレート一式`** のときは **workflow-specification.md**「Tag Mode テンプレート一式」に従い、**汎用** `variant_id` をエージェント独断で省略しない。**カスタム**は作品メタの**カスタム要素**に列挙したときのみ追加（共有ルールにジャンル固有 ID を固定しない）。
- **互換 Markdown の `## 1.` など**: `tools/novel_prompt_ir_export_md.py` は、`prompt_variants` の **配列の並び順**に従い、状況ブロック見出しを `## 1.` `## 2.` … と付ける。**見出しの連番は `variant_id` の先頭数字から自動算出されない**（先頭要素が必ず `## 1.` に対応する）。
- **検証ツール**: `tools/novel_prompt_ir_validate.py` は、漫画ページなどとの **参照整合**（存在しない `variant_id` を指していないか等）は確認するが、**`NN_short_slug` 形式かどうかは検証しない**。

見出し番号と管理用 ID を一致させたい場合は、`prompt_variants` を **`000` → `001` → … → `100` → `101`** の数値昇順に並べ、互換 MD の見出しは **`## NNN.`**（`variant_id` 先頭3桁）に揃える。

## 重要: キャラクターの「固定タグ」と「バリアントタグ」の分離（混入事故防止）

`CharacterPrompt` の固定タグは **`000_base.danbooru_tags` のみ**を正本とする（`CharacterPrompt.fixed_prompt_tags()` / `tools/manga_prompt_ir/character_fixed_tags.py`）。
漫画 batch の主経路（`character_ir_tags()`）も **`000_base` + `variant_id` + `combines_with`** で解決する。ルートの **`character_tags` は 2026-06 以降廃止**。

具体的には、`fixed_prompt_tags()` が返す **`000_base.danbooru_tags`** が、各バリアント合成の土台として毎回混ざる。

**副経路**（`novel_prompt_ir_embed_snapshots`、`prompt_renderer` の snapshot 未使用時等）では、従来どおり `manga_rules.consistency_tags` や `appearance.distinctive_features` が **追加注入され得る**（`workflow-specification.md`「Tag Mode 身体的正本（3階層継承）」参照）。

### ルール（推奨）

- **固定に入れてよい（全シーン不変）**
  - 髪色・髪型の核（例: black_hair / silver_hair）
  - 目色、肌、体格の核（例: brown_eyes / fair_skin）
  - 種族特徴（例: pointed_ears 等）
  - 固定小物（例: 星型ヘアピン等、常に付ける前提のもの）
  - 「絶対に変えてはいけない」一貫性タグ（`manga_rules.consistency_tags` / `manga_rules.do_not_change`）

- **固定に入れない（バリアントへ寄せる）**
  - 通常服／水着／鎧など、**状況で切り替わる衣装タグ**
  - standing / sitting のような姿勢タグ（状況で変わる）
  - 屋外・屋内・背景（作品側/コマ側で管理）
  - **露出・性器・裸限定タグ**（→ **`006_nude`（身体的正本）** および **`combines_with: 006_nude` の Level 3**）
  - **`character_id` / `name` / `name_en` 相当の人名・キャラ名トークン**（メタ情報として YAML ルートに残し、**`danbooru_tags` 列には入れない**。既存学習キャラへの引きずり防止）

### 身体的正本（3階層継承・Tag Mode 作成順）

NSFW を扱う作品では、新規 YAML 作成時の思考順を固定する。

1. **Level 1（SFW）**: `000_base` — 髪・目・肌・種族のみ。`appearance.height` には **`character.md` の身長**を写す（必須。`novel_character_md_check.py --profile visual` と整合）。`appearance.distinctive_features` / `consistency_tags` にも **裸限定タグを置かない**。
2. **Level 2（NSFW）**: `006_nude` — `nude`, `uncensored`, 性器・秘部詳細の**唯一のタグ正本**。
3. **000番台（着衣）**: `001_normal` 等 — 衣装・半脱衣装のみ。裸露本体は載せない。
4. **Level 3（状況）**: `007_arousal`, `008_relax`, `103_*` 等 — **`combines_with: 006_nude` 必須**。表情・体液・行為タグのみ。
5. **100番台（資料）**: `100_intro` 等 — 平服資料は `combines_with: 001_normal`、裸資料は `combines_with: 006_nude`。

Level 1 禁止事項（着衣漏洩防止）: 主経路の character_ir_tags() は 000_base 優先に改修済み。それでも distinctive_features / consistency_tags に裸限定タグがあると、embed・renderer 等の副経路で着衣コマに漏れうる。Tag Mode では Level 1 から裸限定タグを除外すること。

検証: `python tools/novel_prompt_ir_validate.py novels/<作品>`（身体的正本 WARNING、人名トークン WARNING、`--strict-quality` で ERROR 化可）。

### 実装メモ（確認ポイント）

この混入は「base_caption」というフィールド名の有無に関わらず、**固定タグの合成方式**が原因で起きる。
スキル運用では、固定タグ＝不変、バリアントタグ＝可変、という分離で事故を防ぐ。

### ツール連携（衣装タグが「ついてくる」ときの確認順）

次のバッチはいずれも、キャラ YAML の **固定合成**（上記 `fixed_prompt_tags()` 経路）に依存する。

- **`tools/image_provider_novel_tag_batch.py`**: 各 `prompt_variants` のプロンプト組み立てで、平服等を `costume.outfit_tags` に置くと **全バリアントに衣装が残留**しうる。
- **`tools/novel_prompt_ir_export_md.py`**: `tag/<romaji>.md` の互換出力は YAML IR を正とする。IR を直したら **再エクスポート**して Markdown を更新する。**漫画**の `manga/manga_XX.md` を出すときは下記「互換 Markdown エクスポートの既定」とおり **`--novelai-pipe-tags` を付ける**。
- **`tools/novel_prompt_ir_embed_snapshots.py`** → **`tools/image_provider_novel_manga_batch.py`**: ページ YAML の `character_snapshots` はキャラ IR から埋め込まれる。**`outfit_tags` の誤りは漫画コマ生成にも波及**する。IR 修正後は対象作品で `embed_snapshots` を再実行し、必要なら漫画ページ YAML をコミットし直す。

**改稿チェックリスト（最短）**

1. `tag/characters/<id>.yaml` で **`costume.outfit_tags` を空か固定小物のみ**にし、衣装は **`prompt_variants[].danbooru_tags`** に寄せる。
2. 互換 Markdown を出す: キャラのみ `python tools/novel_prompt_ir_export_md.py --character ... --output-dir novels/<作品>`。**漫画**の `manga/manga_XX.md` も出す場合は `--manga-page` にページ YAML を列挙し、**`--novelai-pipe-tags` を付ける**（上記「互換 Markdown エクスポートの既定」）。
3. 漫画を既に持つ作品なら `python tools/novel_prompt_ir_embed_snapshots.py novels/<作品>` でスナップショット更新 → `python tools/novel_prompt_ir_validate.py novels/<作品>` で確認。

人間向きの記述の正本は **`_how_to.example/tag.md`**（ユーザー領域の `_how_to/tag.md` はローカル調整可）の「YAML IR の `costume.outfit_tags`」節。

## `--novelai-pipe-tags` の規則（漫画エクスポート時）

> エクスポートの**手順・完了条件**はスキル **`novel-manga-md-output`** を正とする。本節は Step1 タグ形式に関わる **フラグの規則**のみを扱う。

`tools/novel_prompt_ir_export_md.py` で `manga/manga_XX.md` を出力するとき、**`--novelai-pipe-tags` を必ず付ける**。

- Step1 の各コマ `tag` 行が `ベース側 | キャラ側`（NovelAI の `|` 分割）になり、`image_provider_novel_manga_batch.py`（`provider=novelai`・`--source step1-panels`）のプロンプト形状と整合する。付けないと Step1 がカンマ区切り1本になり、バッチの前提とずれる。
- **例外**: `--manga-page` を渡さずキャラクター互換（`tag/<character_id>.md`）だけを出す実行では Step1 `tag` 行がないため不要。
- **Step2**: `--novelai-pipe-tags` の有無で Step2 本文は変わらない。ただし漫画ファイルを一括エクスポートするコマンドでは付けておくと手順が一本化される。

詳細はスキル **`image-provider（旧 forge-txt2img）`**（NovelAI の `|` 区切り）も参照。

## 移行ルール

既存の Markdown 資産は、すぐに破棄しない。互換 Markdown は、人間の手作業・差分確認・既存バッチ向けの**可読な副本**として継続する。

- `tag/<romaji>.md` は `character.yaml` へ写経・正規化し、`Danbooru Tags` 行を **`tools/image_provider_novel_tag_batch.py` 向けにエクスポート**する先として残す（人間が読み・直す作業面でも重要）。
- `manga/manga_XX.md` はページ YAML へ写経・正規化し、Step1 / Step2 を **`tools/image_provider_novel_manga_batch.py` 向けにエクスポート**する先として残す（ページ単位の推敲・共有にも使う）。
- 既存作品にある `manga/manga_*.md` は、削除・退避を既定にしない。YAML が正本、Markdown は同階層に置く副本・生成物として扱い、通常運用では `--input yaml` を使う。Markdown を手で直した場合は、対応する `manga/pages/*.yaml` に戻してから再エクスポートする。
- 画像生成では **YAML を正本**とし、必要に応じて Markdown 互換ブロックを **エクスポートで生成**する。
- 既存ツールを正式に更新するときは、`tools_temp/` で抽出・変換を試作してから `tools/` へ整理して反映する。

## 画像バッチとの連携（ファイル名と出力増殖）

`tools/image_provider_novel_manga_batch.py`（コマ生成 `step1-panels` 等）は、各ページYAMLの保存プレフィックスに使う **ページ番号 `pNN`** を、**YAML本文ではなくファイル名**から取る（`manga/pages/manga_01_p03.yaml` → ページ 3）。実装は `yaml_page_number()` がファイル名末尾の `_p(\d+)` を読む方式。

- **`meta.page_count`** は「このファイルが何ページ分の定義か」（多くは `1`）であり、章内連番のページ番号ではない。ページ番号の人間可視の正は **`manga_XX_pNN.yaml` の `NN`**。
- ファイル名に `_p数字` が無い場合は列挙順のインデックスにフォールバックするため、命名ミスで **常に先頭ページ扱い** に寄ることがある。
- `tools/image_provider_generate.py` は `{file_prefix}_{timestamp}_{seed}.png` 形式で保存するため、**再実行のたびにファイルが増え上書きしない**。期待枚数より多いPNGは古い試行の残骸の可能性が高い。

## 必須チェック

生成または改稿した YAML は、次を満たすこと。

- **`panels[].prompt_tags` を触ったタスクでは**、`_how_to/manga_tag.md` を読み、置き換え・NSFW 表記・除外タグの慣例を **`prompt_tags` に反映した**（上記「`manga_tag.md` との役割分担」）。
- YAML が Pydantic モデルで検証できる。
- 自然文プロンプトを生成できる。
- タグ列を生成できる。
- テキスト要素だけを抽出できる。
- `render_instruction.prompt_header` / `panel_policy` / `character_policy` が入り、YAML単体で作画依頼として成立する。
- キャラクター固定特徴が、登場するすべてのコマへ引き継がれる。
- ページ単位で、コマ数、読み順、段・大小・視線誘導のいずれかが読める。
- **`background_concepts[]`**: Manga Tag Mode では上記「`background_concepts[]`（Manga Tag Mode）」に従い、**1ページ最低1件**（シーン最初のページは establishing 系を含む）を原則とする。各件に `concept_id` / `title` / `description` / `prompt` があり、人物なしの背景資料として読める。空間に加え **UI・小道具・反復オブジェクト** も載せてよい。

## 参考コマンド

依存パッケージはリポジトリルートで導入する。

```bash
python -m pip install -r requirements.txt
```

スキーマ・コンバーターのテスト:

```bash
python -m pytest tools/manga_prompt_ir/tests
```

作品フォルダ内のIR検証:

```bash
python tools/novel_prompt_ir_validate.py novels/<作品フォルダ>
```

YAML/JSON IR から既存バッチ互換 Markdown を出力（**漫画 `manga_XX.md` 含有時は `--novelai-pipe-tags` を付ける**）:

```bash
python tools/novel_prompt_ir_export_md.py \
  --character novels/<作品>/tag/characters/<character_id>.yaml \
  --manga-page novels/<作品>/manga/pages/manga_01_p01.yaml \
  --output-dir tools_temp/ir_export_sample \
  --manga-stem manga_01 \
  --novelai-pipe-tags
```

**互換 Markdown（副本）の出力場所・中身（ツール実装と一致させる）**

- 保存先は **`{--output-dir}/manga/{--manga-stem}.md`**。`--output-dir` は **作品フォルダ**（例: `novels/<作品>/`）を渡す。`novels/<作品>/manga` を `--output-dir` にすると **`manga/manga/manga_XX.md`** のように一段深くなり、ルールで想定する `novels/<作品>/manga/manga_XX.md` とずれる。
- 章の全ページを **1ファイルの副本** にまとめるときは、`--manga-page` に **`manga_01_p01.yaml` … `p06.yaml` を列挙した1回の実行**で出す。ページごとに別コマンドで上書きすると、**最後に渡したページ分だけ**になる。
- 生成される Markdown は先頭に **IR正本パス一覧**、続けて **各 YAML 1ファイルあたり `## Page N` → `### Step1` / `### Step2`**（コマ説明・`tag` 行・和訳）。内容の正本は常に **`manga/pages/*.yaml`**。
- **`### Step2` の各コマ行**は、レイアウトと **コマ要約**（`panels[].step2_summary` があればそちらを優先、無ければ `summary`）に加え、**`--character` で渡した** `tag/characters/*.yaml` およびページ IR の **`character_snapshots[]`**（**`appearance_summary` のみ**を【固定見た目】に使う。`costume_summary` は含めない）から **`【固定見た目】`** を自動付与する。実装は `tools/image_provider_novel_manga_batch.py` の `panel_step2_description` / `build_step2_panel_line`（`yaml_page_step2_text` も同じ）。

依存関係:

- Pydantic v2
- PyYAML
- pytest

## 関連スキル

- `novel-tag-md-format`: 既存 Markdown 互換のキャラクタータグ形式
- `novel-tag-character-consistency`: キャラクター固定特徴の照合
- `manga-tag-character-sync`: 漫画コマへのキャラクター特徴継承
- `manga-tag-quality-gate`: 主語・行為・レイアウトの品質確認
- `image-provider（旧 forge-txt2img）`: 生成プロバイダへの最終受け渡し
