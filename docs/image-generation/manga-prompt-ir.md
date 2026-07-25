# 漫画ページ IR（manga-prompt-ir）とツール・パイプライン

**読者**: リポジトリの **操作マニュアル**（`docs/`）として、YAML の正本置き場・検証・画像生成バッチまでの**機械的な手順**を扱います。

**扱わないこと**: コマの英語タグの語彙表・置換ルール（→ [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)）。物語の書き方・レイアウトの創作指針（→ [`_how_to.example/manga.md`](../../_how_to.example/manga.md)）。Step2 の**具体語→構図の言い換え表**（→ [`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)）。互換 Markdown の Step1/Step2 の**長文テンプレと叱り方の全文**（→ [manga-tag-generation.md](manga-tag-generation.md)）。

**本書で扱うこと**: 後述の「ページ YAML の最小構造と Step1 互換出力の元」で、**IR のフィールド形**と **エクスポート先の Step1 との関係**を述べる（創作技法ではなくドキュメント）。

---

## このドキュメントを使う場面（人間の操作視点）

### どんな場面で使うか

- 小説本文（`_novel_text/`）が書けていて、それを**漫画ページとして画像化したい**とき
- Monogatari Coach に「漫画タグを作って」と指示したあと、**何が生成されて、どこを確認すればよいか**を知りたいとき
- 生成した YAML を検証・修正して、画像生成バッチに渡すまでの手順を確認したいとき

前提条件: `character.md` と `tag/characters/*.yaml` にキャラクターの外見定義が揃っていること。

### チャットへの指示文

```
本文から漫画タグを作成してください。
```

これだけで動きます。Monogatari Coach は、ルールに従って本文・キャラクター定義の参照から YAML 作成・検証・互換出力までを自動で進めます。

対象の章や追加条件を指定したいときは、以下のように補足できます。

```
novels/NNN_作品名/_novel_text/novel_text01.md を参照して、第1章の漫画タグを作成してください。
```

### Monogatari Coach が行うこと

1. 本文を読んでコマ・ページに分解する
2. `novels/<作品>/manga/pages/manga_XX_pYY.yaml` を作成する（ページ定義の正本）
3. `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` で型・参照・品質を検証する
4. 必要なら `python tools/novel_prompt_ir_export_md.py` で互換 Markdown（`manga/manga_XX.md`）を出力する（**チャットやエージェントの Write だけでは不可**。完了条件は `.rulesync/rules/concepts.md` の「漫画互換Markdownの完了条件」・スキル `novel-manga-md-output`）

### ユーザーが確認できるもの

| 確認対象 | 場所 |
|---------|------|
| 作成された YAML（正本） | `novels/<作品>/manga/pages/manga_XX_pYY.yaml` |
| 検証結果（型・品質の警告） | コンソール出力 |
| 互換 Markdown（可読副本） | `novels/<作品>/manga/manga_XX.md`（出力した場合のみ） |
| 画像の保存先（コマ・ページ） | `novels/<作品>/manga/_assets/<manga_XX>/comic/`（画像生成後） |
| 背景資料 | `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` |

画像生成を実行するときは [Image Generation](index.md) の手順に従い、`--dry-run` で確認してから本番実行します。

---

## 正本と入出力

正本・副本の横断定義は [概念正本](../../.rulesync/rules/concepts.md) の「漫画IRと互換Markdown」にあります。このページでは、人間が実際に確認するファイルとコマンドの流れだけを説明します。

| 役割 | パス |
|------|------|
| ページ定義の正本 | `novels/<作品>/manga/pages/manga_XX_pYY.yaml` |
| スキーマ（Pydantic） | `tools/manga_prompt_ir/schemas/manga_page.py` |
| 互換 Markdown（人間向けの副本・再生成・バッチ用） | `novels/<作品>/manga/manga_XX.md`（**ページ定義の唯一の正本にしない**。推敲・可読参照に用いる） |
| キャラ外見の正本 | `tag/characters/<character_id>.yaml` |

**Manga Tag Mode**: 初手は **YAML IR 作成** → `novel_prompt_ir_validate.py` → 必要なら `novel_prompt_ir_export_md.py`。`manga_XX.md` を直接新規作成して正本にしない。

既存作品にある `manga/manga_*.md` は削除や退避を前提にせず、**YAML から再生成できる人間向け副本**として同じ場所に保管します。通常運用・検証・画像生成は `manga/pages/*.yaml` を正本にし、Markdown を手で直した場合はその変更を YAML へ戻してから再エクスポートします。差分確認や外部連携で Markdown が必要なときだけ使い、判断に迷う古い Markdown は `_legacy/` へ移すより、まず対応する YAML の有無を確認します。

---

## 本文 → YAML → 画像 までのフロー

```
[本文 _novel_text/novel_textXX.md]
  ↓ 読み込み・コマ化
[manga/pages/manga_XX_pYY.yaml]  ← 正本（ここを編集する）
  ↓ python tools/novel_prompt_ir_validate.py（型・参照・品質）
  ├─ tools/image_provider_novel_manga_batch.py --input yaml --source step1-panels（コマ生成）
  ├─ tools/image_provider_novel_manga_batch.py --input yaml --source step1-pages（精密ページ生成）
  ├─ tools/image_provider_novel_manga_batch.py --input yaml --source step2-pages（ページ生成）
  └─ tools/image_provider_novel_manga_batch.py --input yaml --source background-concepts（背景資料）
      ※ Manga Tag 作成時: 各ページ YAML に background_concepts[] を原則1件以上（詳細は .rulesync/skills/manga-prompt-ir/SKILL.md）

必要な場合だけ:
  ↓ tools/novel_prompt_ir_embed_snapshots.py（スナップショット埋め込み）
  ↓ tools/novel_prompt_ir_export_md.py（互換 Markdown）
[manga/manga_XX.md]  ← 互換出力・人間向けの副本（正本は YAML。変更は YAML→再エクスポート）
```

- 本番前は `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` を推奨。
- 通常は `--input yaml` が既定。旧 Markdown 互換だけ `--input markdown`。
- 修正は **常に YAML 側**。`manga_XX.md` が要るときだけ再エクスポート。
- **Step1 の `tag` 行（画像向けトークン列）は英語のみを載せる**: `tools/manga_prompt_ir/scene_prompt.py` が `image_provider_novel_manga_batch` / `novel_prompt_ir_export_md` から呼ばれ、**`composition` / `camera` / `lighting` / subject の状況語**は **`*_en` を優先**し、旧フィールドは **CJK を含まない場合のみ**タグに含める（日本語メモがタグに漏れない）。確実に載せたい語は **`focus_en`**, **`pose_action_en`**, **`expression_en`**, **`panels[].mood_atmosphere_en`** などを YAML に書く。

### コマ要約の英訳（`summary_en`）と NovelAI 併用

各 `panels[]` には **`summary`（日本語）** と **`summary_en`（英語）** をペアで持たせる。横断正本は **`.rulesync/rules/concepts.md`** の「Manga `summary_en` の翻訳経路」。

**主経路（既定）**: Manga Tag Mode で `summary` を書いた同ターンに、エージェントが **`summary_en`** と **`summary_en_source`（= そのときの `summary` 原文）** を YAML に記入する。`location_en` / `pose_action_en` と同型。

```bash
# 検証（欠落・鮮度・CJK は警告、--strict-quality で失敗＝完了ゲート）
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality
```

**任意経路（一括再翻訳）**: エージェントなしで `summary` だけ直したとき、または Chat API で一括翻訳したいとき。

```bash
python tools/novel_manga_panel_summary_en.py novels/NNN_作品名
# 要: MONOCRI_SUMMARY_EN_* と OPENAI_API_KEY または OPENROUTER_API_KEY
```

- **`summary_en_source`**: 翻訳時点の `summary` 原文。`summary` を直したあと不一致なら再翻訳が必要（validate が検出）。
- **コマ生成**: `step1-panels` では既定で **`summary_en` をベースタグ列に併用**（`prompt_tags` と同じプロンプト内）。無効化は `--no-include-panel-summary` または `MONOCRI_MANGA_STEP1_INCLUDE_PANEL_SUMMARY=0`。
- 翻訳ツール用環境変数（任意経路のみ）: `MONOCRI_SUMMARY_EN_MODEL`（既定 `gpt-4o-mini`）、`MONOCRI_SUMMARY_EN_PROVIDER`（`openrouter` 可）。**主経路では未設定でもよい**。

### ページ生成の provider 別 formatter

`--source step1-pages` / `--source step2-pages` は、YAML から作った既存のページ指示文を素材にしつつ、provider 設定に応じて `tools/manga_prompt_ir/prompt_formatters.py` の formatter を通します。Grok / OpenAI / OpenRouter 系の既定は `manga_page_instruction` で、英語の `Page Structure` / `Panel Outline` / `Character Anchors` / `Do not include` を添え、`negative_prompt` は prompt 内の `Do not include` へ移します。

```bash
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-pages --provider grok_pro --dry-run

python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages --provider grok_pro --dry-run
```

`--prompt-formatter tag_csv` を付けると、旧来の日本語ページ指示文と native `negative_prompt` の形に戻して比較できます。既定値は `config/image_generation.json` の `providers.*.prompt_formatter` で管理します。

### コマ生成の provider 別 formatter

`--source step1-panels` も同じ resolver を通ります。既定では、NovelAI は `novelai_pipe` のまま **`ベース | キャラ`** 形式と native `negative_prompt` を維持し、Forge は `tag_csv` を維持します。Grok / OpenAI / OpenRouter 系は `natural_sections` になり、1コマ分の `Panel Context` / `Characters` / `Composition` / `Lighting and Mood` / `Visual Tag Hints` / `Do not include` へ整理します。

```bash
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels --provider grok_pro --dry-run

python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels --provider novelai --dry-run
```

NovelAI で `|` 分割を使わない比較は、従来どおり `--no-novelai-pipe-character-tags` を付けます。この場合、effective formatter は `tag_csv` と表示されます。

**キャラ単独トークン（tag_csv / pipe base）**: `tag_csv`（`yaml_panel_tags`・挿絵バッチ含む）および `novelai_pipe` のベース列では、`character_id` / `name_en` / `name` と一致するトークン（例: `focus_en: yuna`、誤って入った `Tsumugi`）を `character_token_filter` で除外する。`yaml_panel_tags` は人名を後付けしない。`focus_en` はキャラ ID 単体ではなく構図タグ（例: `lying figure on bed`）を書く（`.rulesync/skills/manga-prompt-ir/SKILL.md`）。pipe のキャラセグメント先頭 `name_en` は今回の除外対象外。

### 互換 Markdown を出すとき（`novel_prompt_ir_export_md.py`）

**`--manga-page` を渡す実行では、手順を一本化するため `--novelai-pipe-tags` を付ける**と、Step1 の各コマ `tag` 行が NovelAI 向け **`ベース | キャラ`** 形式になり、`image_provider_novel_manga_batch`（step1-panels 等）と形が揃います。付けないと Step1 がカンマ一列になりやすい。

---

## よく使うコマンド（IR 周り）

```bash
# 検証（作品フォルダ内の character + manga pages を一括）
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality

# スナップショット埋め込み
python tools/novel_prompt_ir_embed_snapshots.py novels/NNN_作品名

# 互換 Markdown 出力（例: 第1章6ページ）
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/foo.yaml \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml \
  ... \
  --output-dir novels/NNN_作品名 --manga-stem manga_01 --novelai-pipe-tags
```

画像生成バッチの具体例・`--dry-run`・provider は [index.md よく使うコマンド](index.md#よく使うコマンド) と [`image-provider`（旧 `forge-txt2img`）スキル](../../.rulesync/skills/forge-txt2img/SKILL.md) を参照。

---

<span id="yaml-minimal-step1"></span>

## ページ YAML の最小構造と Step1 互換出力の元

`novels/<作品>/manga/pages/manga_XX_pYY.yaml` は **Manga Tag Mode の正本**です。`tools/novel_prompt_ir_export_md.py` が互換 `manga/manga_XX.md` を出力するとき、**`### Step1`** ブロック（各コマの説明文・翻訳・`tag:` 行の素材）は、この YAML の `panels[]`・`manga`・`scene`・`render_instruction` 等から組み立てられます。**互換 Markdown の Step1 は「ページ YAML をどう書いたか」のエクスポート結果**であり、創作技法ファイル（`_how_to/manga.md`）ではなく **本ドキュメントとスキーマ**が型の参照先になります。

- **型の正本**: `tools/manga_prompt_ir/schemas/manga_page.py`（`MangaPagePrompt`）
- **検証**: `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality`
- **スキル総説**: [manga-prompt-ir/SKILL.md](../../.rulesync/skills/manga-prompt-ir/SKILL.md)
- **画風トークン（`manga.genre_tags` / `visual_tags`）**: フルカラー生成を前提にするなら、**原則 `monochrome`・`screentone` を入れない**（`novel_prompt_ir_export_md.py` が各コマの互換 Step1 `tag` 行に連結するため）。例外・語彙の目安は創作技法 [`_how_to/manga.md`](../../_how_to/manga.md)（雛形 [`_how_to.example/manga.md`](../../_how_to.example/manga.md)）の「`manga.genre_tags` / `manga.visual_tags`」節。

---

## ページ別の指示メモ（強制追加・強制削除）

実行自体は問題なく動いているのに、生成結果の品質修正で「何を直すべきか」がブレる場合は、ページ YAML に **ページ別の指示メモ**（ユーザ指示の正本）を置きます。

### どこに書くか

- ページ単位（正本）: `render_instruction.user_directives`
  - `page_notes[]`: 自然文の指示（品質修正の軸）
  - `defaults.required_prompt_tags[]`: 全コマへ必ず追加する `prompt_tags`
  - `defaults.omit_prompt_tags[]`: 全コマから必ず除外する `prompt_tags`
- コマ単位（上書き）: `panels[].required_prompt_tags[]` / `panels[].omit_prompt_tags[]`

### どう効くか（適用順）

1. 既存の Step1 タグ列（`prompt_tags` など）を組み立てる
2. `defaults.required_prompt_tags` → `panels[].required_prompt_tags` の順で **必ず追加**
3. `defaults.omit_prompt_tags` ∪ `panels[].omit_prompt_tags` を **必ず除外**

これらは次に反映されます。

- `tools/image_provider_novel_manga_batch.py`（YAML入力の Step1: `step1-panels` 等）
- `tools/novel_prompt_ir_export_md.py`（互換 Markdown の Step1 `tag` 行）
- `tools/novel_prompt_ir_validate.py`（矛盾・二重記載の警告）

### 用例（強制追加）

```yaml
render_instruction:
  user_directives:
    page_notes:
      - このページは「プールの描写（空気感・水面・反射）」を深めたい
    defaults:
      required_prompt_tags:
        - swimming_pool
        - rippling_water
        - reflections
      omit_prompt_tags: []
```

### 用例（強制削除）

屋外の背景タグが混入しがちなページで、屋内を徹底したい場合の例です。

```yaml
render_instruction:
  user_directives:
    page_notes:
      - 屋内シーンなので屋外タグの混入を禁止する
    defaults:
      required_prompt_tags: []
      omit_prompt_tags:
        - outdoors
        - sky
```

### 用例（コマ単位の上書き）

ページ全体はそのままに、特定のコマだけ「必ず入れる／外す」を上書きしたい場合の例です。

```yaml
panels:
  - panel_id: 3
    summary: 接写のコマ
    prompt_tags: ["close-up", "water_droplets"]
    required_prompt_tags: ["rippling_water"]
    omit_prompt_tags: []
```

### 用例（このページからこのページへ：強制追加・強制削除）

「このページ（の途中）から次のページ（の冒頭）まで」という範囲指定は、**ページ単位の defaults** と **コマ単位の上書き**を組み合わせて表現します。

- **強制追加（ポジ例）**: `manga_02_p08.yaml panel_id=3` から `manga_02_p12.yaml panel_id=1` まで、プールの空気感タグを必ず入れる
  - `manga_02_p09.yaml`〜`manga_02_p11.yaml` は `render_instruction.user_directives.defaults.required_prompt_tags` に書く
  - 範囲の端点（`p08:3` / `p12:1`）だけ `panels[].required_prompt_tags` で上書きする

- **強制削除（ネガ例）**: 同じ範囲で、屋外っぽいタグが混ざるのを防ぐ
  - 中央ページ（`p09`〜`p11`）は `defaults.omit_prompt_tags` に書く
  - 端点（`p08:3` / `p12:1`）だけ `panels[].omit_prompt_tags` を使う

### §5 漫画タグ層を YAML へ一括転記する

`_meta.md` §5 の「漫画タグ層（区間・常時上乗せ）」テーブルを合意したあと、各ページ YAML の `render_instruction.user_directives.defaults` へ手で複写するのを忘れないようにするためのツールです。

まず dry-run で転記内容を確認します。

```bash
python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル
```

内容を確認したら `--apply` を付けて実際に書き換えます。

```bash
python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル --apply
```

実行後、各ページ YAML に `defaults.required_prompt_tags` / `defaults.omit_prompt_tags` が設定され、`page_notes` に `_meta §5: <区間>` の追跡メモが追記されます。

- **`_meta.md`** が見つからない場合や §5 テーブルが空の場合は、その旨が表示されて終了します。
- `--no-note` を付けると `page_notes` への追記を省略できます。
- 既に同じ `_meta §5:` エントリが `page_notes` にある場合は重複追記しません。

---

以下は **`MangaPagePrompt` に沿った**最小例です（フィールド名・入れ子はスキーマが正本）。**実作品の具体例**としては同フォルダの `*.yaml` が最も手堅いです。

### スキーマ主要フィールドの説明

| フィールド | 説明 |
|-----------|------|
| ファイル名 / `meta` | ファイル名（`manga_01_p01.yaml` 等）で章・ページを表現。`meta.intent: manga_page`、`reading_order: right_to_left`（または `left_to_right`）。ほかに `aspect_ratio`・`page_count` |
| `manga.genre_tags[]` / `manga.visual_tags[]` / `manga.panel_layout` | 画風・モノクロ／カラーはここと `color_palette` で設定 |
| `scene.time_of_day` | 任意。画像用英語は `time_of_day_en` |
| `scene.background_notes` / `background_notes_en` | `background_notes` は編集用に日本語可。**タグ行・バッチは `background_notes_en` のみ**（日本語にはフォールバックしない。欠けると `MangaPagePrompt` 検証エラー）。または `prompt_tags` / `background_concepts[]` |
| `panels[].panel_id` | 整数。コマの識別子 |
| `subjects[].pose_action` / `subjects[].description` | `description` は必須文字列（キャラでも背景オブジェクトでも） |
| `composition` / `camera` | 別オブジェクト。アングルは `camera.angle`、画角は `camera.shot_size` など |
| `text.dialogue[].content` | 台詞のテキスト本体 |
| `prompt_tags: []` | 文字列のリスト（単一文字列ではなく配列） |
| `render_instruction` | `task` / `prompt_header` / `panel_policy` / `character_policy` が実質の運用で常用 |
| `scene.location_en`（必須・非空） | `background_notes` / `time_of_day` / `weather` を記載した場合は対応する `*_en` も必須。背景 subject の `description_en` なども同様（詳細は [manga-prompt-ir/SKILL.md](../../.rulesync/skills/manga-prompt-ir/SKILL.md)） |
| `color_palette.mode` | `monochrome` / `limited_color` / `full_color` |
| `character_snapshots[]` | 本番では `novel_prompt_ir_embed_snapshots.py` で埋めるか手書きで整合させる |
| `panels[].negative_tags` / `panels[].omit_negative_tags` | 任意・コマ単位 txt2img 向け。語彙は [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)「コマ別ネガ」 |

### 色モードと `manga.visual_tags`

ページ単位の色モード正本は `color_palette.mode` です。`manga.visual_tags` は生成タグとして効く補助情報なので、原則として次のように揃えます。

| `color_palette.mode` | `manga.visual_tags` の目安 |
|----------------------|-----------------------------|
| `monochrome` | `monochrome`, `screentone`, `black and white` など |
| `limited_color` | `limited_color`, `accent_color`, `spot_color` など。必要ならモノクロ系タグと併用可 |
| `full_color` | `full_color`, `colorful`, `anime coloring` など。原則 `monochrome` / `screentone` は入れない |

優先順位は、CLI `--color-mode`（その実行だけ） > YAML の `color_palette.mode` > `.env` の `MONOCRI_MANGA_COLOR_MODE_DEFAULT` > スキーマ既定 `monochrome`。`novel_prompt_ir_validate.py` はモードとタグ・`render_instruction` の矛盾を WARNING として出しますが、センターカラーや扉絵だけカラーなどの意図的例外を想定し、通常運用では YAML の自動修正や通常エラー化はしません。

```yaml
schema_version: '1.0'
meta:
  intent: manga_page
  reading_order: right_to_left
  aspect_ratio: '2:3'
  page_count: 1
render_instruction:
  task: このYAMLを、漫画1ページ分の作画依頼書として扱う。
  prompt_header: 廃工場夜戦の1ページ。少年向けアクションのリズムで描く。
  panel_policy: panels[] の panel_id 順に作画する。
  character_policy: character_snapshots と登場キャラの外見を一致させる。
manga:
  genre_tags:
    - manga
    - full_color
  visual_tags:
    - clean_lineart
    - speed_lines
  panel_layout: 上段=コマ1（ワイド）｜中段=コマ2・3横並び｜下段=コマ4（大ゴマ）
scene:
  location: 廃工場の内部
  location_en: abandoned_factory_interior
  time_of_day: 夜、非常灯のみ
  time_of_day_en: night, emergency lights only
  background_notes: 廃工場、非常灯の狭い光
  background_notes_en: industrial decay, narrow shafts of emergency light
character_ids:
  - rei
panels:
  - panel_id: 1
    summary: 零が敵の群れを睨む。上段・横幅ほぼ全体の大ゴマ
    subjects:
      - character_id: rei
        variant_id: battle
        description: 剣を構えて敵の群れを正面から睨む零
        pose_action: gripping sword, facing enemy crowd
        expression: 鋭い目つき、傷だらけ
    composition:
      layout: 上段・横幅全体
      framing: wide shot
    camera:
      angle: low angle
      shot_size: wide
    text:
      dialogue:
        - speaker: 零
          content: 来い……全部まとめて斬ってやる
    prompt_tags:
      - dynamic_wide_angle
      - shonen_jump_style
      - dramatic_low_angle
      - blazing_fire_background
color_palette:
  mode: full_color
technical:
  quality_level: high
  negative_tags:
    - low quality
    - blurry
    - deformed
character_snapshots: []
```

※ 上記は型の見本です。**`character_snapshots: []` は空のままでは検証や生成で警告になりうる**ため、実作品では `tools/novel_prompt_ir_embed_snapshots.py` で埋めるか、`tag/characters/*.yaml` と整合したスナップショットを手で書いてください。コマ単位のネガ（`panels[].negative_tags` / `omit_negative_tags`）は**任意**で、不要なら省略する。使う場合は [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)「コマ別ネガ」と、**後述の「コマ生成（`step1-panels`）のネガティブプロンプト合成順」**を参照。

互換 Markdown の Step1 の**長文テンプレ・書き方の叱り方**は [manga-tag-generation.md の「互換出力: step1」](manga-tag-generation.md#互換出力-step1) を参照してください（本節は **IR の形**の説明です）。

---

## コマ生成（`step1-panels`）のネガティブプロンプト合成順

`--input yaml` かつ **`--source step1-panels`** のとき、各コマの `negative_prompt` は `image_provider_novel_manga_batch.py` 内で次の順に合成されます。

1. CLI の `--negative-prompt`（未指定時はツール既定）
2. `technical.negative_tags`
3. `panels[].omit_negative_tags` に書いた断片を、1〜2 の結果から除去
4. `panels[].negative_tags` を追加（重複除去）

**ページ生成**（`step1-pages` / `step2-pages`）では、CLI の `--negative-prompt` と `technical.negative_tags` をページ単位のネガとして扱います。`manga_page_instruction` formatter 使用時は、これらが prompt 内の `Do not include` へ移り、API に渡す `negative_prompt` は空になります。`panels[].negative_tags` / `panels[].omit_negative_tags` は **コマ単位生成向け**です。

語彙・運用例: `_how_to.example/manga_tag.md` の「コマ別ネガ」。

---

## scene の英語フィールド（タグ行）

**`scene.location_en` は必須（非空）**。`background_notes`・`time_of_day`・`weather` を記載した場合は、それぞれ **`background_notes_en`**・**`time_of_day_en`**・**`weather_en`** も必須（`tools/manga_prompt_ir/schemas/manga_page.py` の `Scene` が検証）。タグ組み立ては **`tools/manga_prompt_ir/scene_prompt.py`** が **`*_en` のみ**参照し、日本語キーにはフォールバックしない。

---

## 関連ドキュメント

| 内容 | 参照先 |
|------|--------|
| 生成モード語（コマ／ページ／精密） | [`.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) の Manga 節 |
| スキル総説 | [`.rulesync/skills/manga-prompt-ir/SKILL.md`](../../.rulesync/skills/manga-prompt-ir/SKILL.md) |
| 品質ゲート（主語・レイアウト） | [`.rulesync/skills/manga-tag-quality-gate/SKILL.md`](../../.rulesync/skills/manga-tag-quality-gate/SKILL.md) |
| 互換 Step1/Step2 の**長文指示・例**（本書の型・最小例と対で読む） | [manga-tag-generation.md](manga-tag-generation.md) |
