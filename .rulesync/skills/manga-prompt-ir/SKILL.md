---
name: manga-prompt-ir
description: >-
  漫画ページ・漫画コマ・キャラクター定義を YAML/JSON/Pydantic の中間表現で管理し、
  画像生成向けの自然文プロンプト、タグ列、テキスト要素へ変換する。
targets: ["*"]
---

# Manga Prompt IR

## 目的

キャラクタータグと漫画タグの正本を、従来の Markdown 抽出だけに依存せず、**Pydantic モデルを正**、**YAML を人間編集用**、**JSON を内部処理・機械連携用**として扱う。

このスキルは、次の3つを分離して管理する。

- **キャラクター定義**: 外見・衣装・性格・固定タグ・禁止変更項目
- **漫画ページ定義**: ページ単位のレイアウト、コマ、人物、セリフ、効果音
- **背景概念定義**: ページや章で使う人物なしの背景・空間設計
- **レンダリング**: 画像生成モデルごとの自然文プロンプト、タグ列、テキスト要素抽出

## 正本の優先順位

1. `tools/manga_prompt_ir/schemas/*.py`: Pydantic v2 モデル。構造・必須項目・型の正本。
2. `tools/manga_prompt_ir/examples/*.yaml`: 人間が編集する入力例。作品ごとの YAML はこの形に寄せる。
3. `tools/manga_prompt_ir/converters/*.py`: YAML/JSON を読み、モデル検証後にプロンプトへ変換する参考実装。
4. 従来の `tag/<romaji>.md` / `manga/manga_XX.md`: 既存ツール互換の出力・移行元として扱う。

## ユーザー向けマニュアル（ツール・パイプライン）

創作技法は `_how_to/manga.md` に置き、**コマンド・検証・バッチ・ネガ合成・export フラグ**など運用手順は `docs/` に分離している。

- **`docs/image-generation/manga-prompt-ir.md`**: `novel_prompt_ir_validate.py` / `novel_prompt_ir_embed_snapshots.py` / `novel_prompt_ir_export_md.py`（`--novelai-pipe-tags` 等）、`forge_novel_manga_batch.py` の `--source`、コマ単位ネガの合成順。
- **`docs/image-generation/manga-tag-generation.md`**: 互換 `manga/manga_XX.md` の Step1/Step2 長文テンプレ・実例・レイアウト記述・生成モード別の運用メモ。

## 運用方針

- このIRは、生成途中で壊れたら作り直せる **再生成可能な中間データ**として扱う。正本性の中心は、YAML形式そのものではなく、そこに入っている **日本語の意味・人物関係・場面意図・セリフ帰属**に置く。
- 小説本文からの変換を主体にする場合、最初のIRは荒くてもよい。品質ゲートで意味を補い、必要ならIR全体を再出力する。
- 新規のキャラクタータグは、まず `character.yaml` 相当の構造へ落とす。
- 新規の漫画タグは、まず `manga_page.yaml` 相当の構造へ落とす。
- `character_id` はキャラクター一貫性の主キーとし、ページ側の `character_ids` と各コマの `subjects[].character_id` から参照する。
- セリフ、モノローグ、ナレーション、効果音は混ぜず、`text.dialogue` / `text.monologue` / `text.narration` / `text.sfx` に分ける。
- 漫画ページ YAML を単体で画像モデルへ渡す運用では、`render_instruction` に作画依頼文を入れる。外側の Markdown やチャット冒頭文が無くても、何を描くか・コマ割りをどう扱うか・キャラクター外見をどう継承するかが読める状態を正とする。
- 画像生成モデルが文字描画を苦手とする場合に備え、テキスト要素は `extract_text_elements()` で別処理できる形にする。
- `negative_tags` はキャラクター側とページ側の両方に持たせ、最終レンダリング時に結合する。
- **コマ単位 txt2img**（`forge_novel_manga_batch.py`・`--source step1-panels`）では、
  各コマのネガを **`--negative-prompt` + `technical.negative_tags` + `panels[].negative_tags`** として合成し、
  **`panels[].omit_negative_tags`** に書いた断片（例: `split screen`）を共通ネガから除いてからコマ別ネガを足す。
  スキーマは `tools/manga_prompt_ir/schemas/manga_page.py` の `Panel.negative_tags` / `Panel.omit_negative_tags`。
- 漫画固有タグ（画風・レイアウト・トーン）とキャラクター固有タグ（髪・目・衣装・種族・固定小物）は分けて保持する。
- 背景を先に起こす場合は `background_concepts[]` を使う。背景概念は Grok / OpenAI のような自然文・構造理解が強い provider へ渡し、人物を主役にしない空間設計として生成する。
- **`scene` の日本語と英語**: `location` / `time_of_day` / `weather` / `background_notes` は人間向けに日本語でもよい。**タグ行・バッチは `location_en` / `time_of_day_en` / `weather_en` / `background_notes_en` のみ**を `tools/manga_prompt_ir/scene_prompt.py` が参照し、日本語キーには**フォールバックしない**。**`location_en` は必須（非空）**。`background_notes`・`time_of_day`・`weather` を書いたときは対応する `*_en` も必須（欠けると `MangaPagePrompt`／`Scene` の検証エラー）。LLM 側で英語行を埋めてから保存する運用を正とする。
- **`subjects[]` の背景・オブジェクト（`character_id` なし）**: `description` は日本語のままでよい。タグ行は **`description_en`** または **`tag_token`** があればそれを使う。**どちらも無く**、`description` が日本語（CJK を含む）のみのときはタグ上は **`subject`** プレースホルダとなり、日本語をタグ列に載せない（`subject_tag_line_token()`）。英語のみの `description` は後方互換でタグに載りうる。
- **`composition` / `camera` / `lighting` とコマの状況語（タグ行）**: Step1 の機械連結タグ（`forge_novel_manga_batch`・`novel_prompt_ir_export_md`）では **`framing_en` / `focus_en` / `perspective_en` / `layout_en`**、**`camera` の `*_en`**、**`lighting` の `*_en`**、**`pose_action_en` / `expression_en`** を優先する。旧キー（`focus` 等）は **CJK を含まないときだけ**タグに載せる（`medium shot` のような英語のみは従来 YAML でも可）。**`panels[].mood_atmosphere_en`** があればタグに使い、無い場合は `mood_atmosphere` のうち CJK を含まない要素のみ。実装の中心は **`tools/manga_prompt_ir/scene_prompt.py`**。

### キャラクターIR・外見初版を新規に起こすとき（`world_wear.md`）

**対象**: `novels/<作品>/tag/characters/<character_id>.yaml` を**新規作成**するとき、または `novels/<作品>/character.md` に**外見・服装の初版**を書き起こすとき（該当キャラの構造化タグ正本がまだ無い／外見が未確定の段階）。**舞台のトーン・配色・服の文化感**を決める前の参照として使う。

**必須動作**（エージェント／人間）:

1. **`_how_to/world_wear.md` を開いて参照する**（ユーザーが `_how_to/` に独自版を置いている場合はそちらを優先。リポジトリ同梱の雛形・索引は **`_how_to.example/world_wear.md`**・**`_how_to.example/_index.md`**）。
2. 得た目安を **`character.md`**、および **`tag/characters/<character_id>.yaml`**（`costume`・`prompt_variants[].danbooru_tags` 等）へ反映する。衣装の**色相**は `white_shirt` のように **Danbooru 系トークンで明示**する運用を推奨（詳細は **`_how_to.example/tag.md`** の衣装・固定タグの節）。

**対象外**（この節を満たさなくてよい）:

- 既存キャラ YAML への**軽微な修正のみ**、**`manga/pages/*.yaml` だけ**の改稿など、**外見正本の新規起こしを伴わない**作業。
- 作品設定が `world_wear` の想定と合わない場合は**当てはまる節だけ**読むか、**参照を省略**してよい（必要なら作品の **`_meta.md`** に「未参照・理由」を一言メモする運用可）。

**備考**: `world_wear.md` はツールが自動では読み込まない創作技法ファイルである。本節は **Tag Mode の初回・キャラ初版づくり**に効き、既存IRの細かな差し替えだけのセッションでは負荷をかけないための区別を置いた。

## `_how_to/manga_tag.md` との役割分担（漫画タグ・語彙・置き換え）

**創作技法としてのコマ割り・ページ設計・IR の組み立て**は **`_how_to/manga.md`**（雛形は `_how_to.example/manga.md`）。**スキーマ・本スキル・`novel_prompt_ir_validate.py`** が構造と品質の正本。**ツール連携の手順の詳細**は **`docs/image-generation/manga-prompt-ir.md`**、**互換 Markdown の Step1/Step2 長文テンプレ・実例**は **`docs/image-generation/manga-tag-generation.md`**。一方、**コマ単位の英語タグ語彙・置き換え・NSFW 表記の慣例**は **`_how_to/manga_tag.md`**（雛形は `_how_to.example/manga_tag.md`）を正とする。**Step2 要約・抽象ページ指示**は **`_how_to/manga_tag_step2.md`**（雛形 **`_how_to.example/manga_tag_step2.md`**）を正とする。

### エージェント／人間の必須動作（ページ YAML を新規・改稿するとき）

1. **`manga/pages/*.yaml` の `panels[].prompt_tags` を書く前に**、必ず **`_how_to/manga_tag.md`** を読む（ユーザーが `_how_to/` をカスタムしている場合はそちらが優先。未編集なら `_how_to.example/manga_tag.md` と同内容を想定）。
1b. **`panels[].step2_summary` を詰める・互換 Markdown の `### Step2` を人間が整える**ときは、**`_how_to/manga_tag_step2.md`**（雛形は `_how_to.example/manga_tag_step2.md`）を**必ず**開く。Step1 の語彙表だけでは足りない（抽象レイアウト・言い換えの作法）。
2. 次を **`prompt_tags` に反映する**（ファイルに書いたルールを機械が自動検証するわけではないため、**人手で反映するまで完了とみなさない**）。
   - **置き換えリスト**: 作品内隠語・言い換えを、 `manga_tag.md` の表に合わせる。
   - **追加ルール**: 該当コマでは `manga_tag.md` の追加ルールに従う。
   - **視点**: `male perspective`, `pov` など、ファイルで推奨されている表記に寄せる。
   - **カラー指向時・ページの `manga` 節**: **原則 `monochrome` と `screentone` を `manga.genre_tags` / `manga.visual_tags` に入れない**（`novel_prompt_ir_export_md.py` が各コマの互換 Step1 `tag` 行へ連結する）。コマの `prompt_tags` だけでなく YAML の **`manga`** を **`_how_to/manga.md`**（雛形 `_how_to.example/manga.md`）の「`manga.genre_tags` / `manga.visual_tags`」節に合わせる。**意図的にモノクロ作品にする場合のみ**例外。コマ単位では従来どおり **`manga_tag.md`** の `screentone` 除外など運用上の禁止・除外も参照。
   - **背景のみ**: `nohuman` 等、ファイルで定義されているルール。
3. **`manga.md` / `manga_tag.md` / `manga_tag_step2.md` / `docs/` を混同しない**: `manga.md` は創作技法としての組み立て；**コマ英語タグの語彙は `manga_tag.md`（Step1 中心）**；**Step2 要約・抽象ページ指示は `manga_tag_step2.md`**；**バッチ・export のコマンド体系は `docs/image-generation/manga-prompt-ir.md`**。`prompt_tags` なら **`manga_tag.md`、Step2 文面なら `manga_tag_step2.md` を開いたか**を確認する。

### ツール側の限界（期待値の調整）

- `novel_prompt_ir_validate.py` は **Pydantic 型・参照・品質ゲート**を検証するが、**`manga_tag.md` の置き換え表どおりかまでは検証しない**。
- 置き換えの自動適用をコードに足す場合は **`tools/`** に実装し、本スキルからパスを参照する（スキルディレクトリに Python を置かない）。

## prompt_variants の `variant_id` と見出し番号（ツールの実際の動き）

キャラクター YAML の `prompt_variants[].variant_id` について、スキーマ・ツールは次のように振る舞う。

- **Pydantic 上の型**: `variant_id` は **任意の文字列**。`_how_to/tag.md` で推奨される **`NN_short_slug`（2桁ゼロ埋め＋アンダースコア＋意味のあるslug）** は **スキーマでは強制されない**。英字のみの ID（例: `normal`）でも検証は通る。
- **命名規約の正本（人間向け）**: バリアントの並べ方・`variant_id` の付け方の詳細は **`_how_to/tag.md` の「バリアント番号（管理用・最小）」** を正とする。差分レビューや `tools/forge_novel_tag_batch.py` の `--variant-id` で特定バリアントだけ生成するときに、`01_normal` のように番号と並びを揃えておくと運用しやすい。
- **互換 Markdown の `## 1.` など**: `tools/novel_prompt_ir_export_md.py` は、`prompt_variants` の **配列の並び順**に従い、状況ブロック見出しを `## 1.` `## 2.` … と付ける。**見出しの連番は `variant_id` の先頭数字から自動算出されない**（先頭要素が必ず `## 1.` に対応する）。
- **検証ツール**: `tools/novel_prompt_ir_validate.py` は、漫画ページなどとの **参照整合**（存在しない `variant_id` を指していないか等）は確認するが、**`NN_short_slug` 形式かどうかは検証しない**。

見出し番号と管理用 ID を一致させたい場合は、`prompt_variants` を意図した順に並べ、あわせて `variant_id` を `01_*`, `02_*` … と **`tag.md` に沿って**付ける。

## 重要: キャラクターの「固定タグ」と「バリアントタグ」の分離（混入事故防止）

`CharacterPrompt` の固定タグは、レンダリング時に **常に全バリアントへ注入される**前提で運用する。
具体的には、`tools/manga_prompt_ir/schemas/character.py` の `CharacterPrompt.fixed_prompt_tags()` が返す次が、毎回（=水着でも治療服でも）混ざり得る。

- `character_tags`
- `costume.outfit_tags`
- `manga_rules.consistency_tags`
- `appearance.species_features`
- `appearance.distinctive_features`

そのため、`costume.outfit_tags`（固定側）に **通常服（平服）** を入れると、**水着バリアントにも通常服タグが混ざる**などの矛盾が発生し得る。

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

### 実装メモ（確認ポイント）

この混入は「base_caption」というフィールド名の有無に関わらず、**固定タグの合成方式**が原因で起きる。
スキル運用では、固定タグ＝不変、バリアントタグ＝可変、という分離で事故を防ぐ。

### ツール連携（衣装タグが「ついてくる」ときの確認順）

次のバッチはいずれも、キャラ YAML の **固定合成**（上記 `fixed_prompt_tags()` 経路）に依存する。

- **`tools/forge_novel_tag_batch.py`**: 各 `prompt_variants` のプロンプト組み立てで、平服等を `costume.outfit_tags` に置くと **全バリアントに衣装が残留**しうる。
- **`tools/novel_prompt_ir_export_md.py`**: `tag/<romaji>.md` の互換出力は YAML IR を正とする。IR を直したら **再エクスポート**して Markdown を更新する。**漫画**の `manga/manga_XX.md` を出すときは下記「互換 Markdown エクスポートの既定」とおり **`--novelai-pipe-tags` を付ける**。
- **`tools/novel_prompt_ir_embed_snapshots.py`** → **`tools/forge_novel_manga_batch.py`**: ページ YAML の `character_snapshots` はキャラ IR から埋め込まれる。**`outfit_tags` の誤りは漫画コマ生成にも波及**する。IR 修正後は対象作品で `embed_snapshots` を再実行し、必要なら漫画ページ YAML をコミットし直す。

**改稿チェックリスト（最短）**

1. `tag/characters/<id>.yaml` で **`costume.outfit_tags` を空か固定小物のみ**にし、衣装は **`prompt_variants[].danbooru_tags`** に寄せる。
2. 互換 Markdown を出す: キャラのみ `python tools/novel_prompt_ir_export_md.py --character ... --output-dir novels/<作品>`。**漫画**の `manga/manga_XX.md` も出す場合は `--manga-page` にページ YAML を列挙し、**`--novelai-pipe-tags` を付ける**（上記「互換 Markdown エクスポートの既定」）。
3. 漫画を既に持つ作品なら `python tools/novel_prompt_ir_embed_snapshots.py novels/<作品>` でスナップショット更新 → `python tools/novel_prompt_ir_validate.py novels/<作品>` で確認。

人間向きの記述の正本は **`_how_to.example/tag.md`**（ユーザー領域の `_how_to/tag.md` はローカル調整可）の「YAML IR の `costume.outfit_tags`」節。

## 互換 Markdown エクスポートの既定（`--novelai-pipe-tags`）

`tools/novel_prompt_ir_export_md.py` で **`manga/manga_XX.md`**（各 `## Page N` 内の **`### Step1`** の **`- **tag**：`** 行を含む）を出力するときは、**エージェント・手動とも次を既定とする**。

- **`--novelai-pipe-tags` を必ず付ける**  
  Step1 の各コマ `tag` 行が **`ベース側 | キャラ側`**（NovelAI の `|` 分割）になり、`tools/forge_novel_manga_batch.py` の **`provider=novelai`・YAML・`--source step1-panels`** が組み立てるプロンプト形状と整合する。  
  **付けないと** Step1 が **カンマ区切りの1本**だけになり、互換 `manga_XX.md` とバッチ実装の前提がずれる。
- **例外（付けない）**: キャラクター互換だけを **`tag/<character_id>.md`** に出す実行（`--manga-page` なし）では、Step1 の `tag` 行が無いため **`--novelai-pipe-tags` は不要**。
- **Step2 との関係**: Step2 ブロックは `panel_step2_description` 系で別組み立てのため **`--novelai-pipe-tags` の有無で Step2 本文は変わらない**。それでも **漫画ファイルを一括エクスポートするコマンドでは付けておく**と、同じ `manga_XX.md` 生成手順が一本化される。

詳細はスキル **`forge-txt2img`**（NovelAI の `|` 区切り）も参照。

## 移行ルール

既存の Markdown 資産は、すぐに破棄しない。

- `tag/<romaji>.md` は `character.yaml` へ写経・正規化し、当面は `Danbooru Tags` の互換出力先として残す。
- `manga/manga_XX.md` は `manga_page.yaml` へ写経・正規化し、当面は Step1 / Step2 の互換出力先として残す。
- 画像生成バッチが Markdown しか読めない間は、YAML を正として Markdown 互換ブロックを生成する。
- 既存ツールを正式に更新するときは、`tools_temp/` で抽出・変換を試作してから `tools/` へ整理して反映する。

## 画像バッチとの連携（ファイル名と出力増殖）

`tools/forge_novel_manga_batch.py`（コマ生成 `step1-panels` 等）は、各ページYAMLの保存プレフィックスに使う **ページ番号 `pNN`** を、**YAML本文ではなくファイル名**から取る（`manga/pages/manga_01_p03.yaml` → ページ 3）。実装は `yaml_page_number()` がファイル名末尾の `_p(\d+)` を読む方式。

- **`meta.page_count`** は「このファイルが何ページ分の定義か」（多くは `1`）であり、章内連番のページ番号ではない。ページ番号の人間可視の正は **`manga_XX_pNN.yaml` の `NN`**。
- ファイル名に `_p数字` が無い場合は列挙順のインデックスにフォールバックするため、命名ミスで **常に先頭ページ扱い** に寄ることがある。
- `tools/forge_generate.py` は `{file_prefix}_{timestamp}_{seed}.png` 形式で保存するため、**再実行のたびにファイルが増え上書きしない**。期待枚数より多いPNGは古い試行の残骸の可能性が高い。

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
- 背景概念を使う場合は、`background_concepts[].concept_id` / `description` / `prompt` があり、人物なしの背景生成として読める。

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
- **`### Step2` の各コマ行**は、レイアウトと **コマ要約**（`panels[].step2_summary` があればそちらを優先、無ければ `summary`）に加え、**`--character` で渡した** `tag/characters/*.yaml` およびページ IR の **`character_snapshots[]`**（**`appearance_summary` のみ**を【固定見た目】に使う。`costume_summary` は含めない）から **`【固定見た目】`** を自動付与する。実装は `tools/forge_novel_manga_batch.py` の `panel_step2_description` / `build_step2_panel_line`（`yaml_page_step2_text` も同じ）。

依存関係:

- Pydantic v2
- PyYAML
- pytest

## 関連スキル

- `novel-tag-md-format`: 既存 Markdown 互換のキャラクタータグ形式
- `novel-tag-character-consistency`: キャラクター固定特徴の照合
- `manga-tag-character-sync`: 漫画コマへのキャラクター特徴継承
- `manga-tag-quality-gate`: 主語・行為・レイアウトの品質確認
- `forge-txt2img`: 生成プロバイダへの最終受け渡し
