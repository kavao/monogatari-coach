# 漫画ページ IR（manga-prompt-ir）とツール・パイプライン

**読者**: リポジトリの **操作マニュアル**（`docs/`）として、YAML の正本置き場・検証・画像生成バッチまでの**機械的な手順**を扱います。

**扱わないこと**: コマの英語タグの語彙表・置換ルール（→ [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)）。物語の書き方・レイアウトの創作指針（→ [`_how_to.example/manga.md`](../../_how_to.example/manga.md)）。Step2 の**具体語→構図の言い換え表**（→ [`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)）。互換 Markdown の Step1/Step2 の**長文テンプレと叱り方の全文**（→ [manga-tag-generation.md](manga-tag-generation.md)）。

**本書で扱うこと**: 後述の「ページ YAML の最小構造と Step1 互換出力の元」で、**IR のフィールド形**と **エクスポート先の Step1 との関係**を述べる（創作技法ではなくドキュメント）。

---

## 正本と入出力

| 役割 | パス |
|------|------|
| ページ定義の正本 | `novels/<作品>/manga/pages/manga_XX_pYY.yaml` |
| スキーマ（Pydantic） | `tools/manga_prompt_ir/schemas/manga_page.py` |
| 互換 Markdown（人間向けの副本・再生成・バッチ用） | `novels/<作品>/manga/manga_XX.md`（**ページ定義の唯一の正本にしない**。推敲・可読参照に用いる） |
| キャラ外見の正本 | `tag/characters/<character_id>.yaml` |

**Manga Tag Mode**: 初手は **YAML IR 作成** → `novel_prompt_ir_validate.py` → 必要なら `novel_prompt_ir_export_md.py`。`manga_XX.md` を直接新規作成して正本にしない。

---

## 本文 → YAML → 画像 までのフロー

```
[本文 _novel_text/novel_textXX.md]
  ↓ 読み込み・コマ化
[manga/pages/manga_XX_pYY.yaml]  ← 正本（ここを編集する）
  ↓ python tools/novel_prompt_ir_validate.py（型・参照・品質）
  ├─ tools/forge_novel_manga_batch.py --input yaml --source step1-panels（コマ生成）
  ├─ tools/forge_novel_manga_batch.py --input yaml --source step1-pages（精密ページ生成）
  └─ tools/forge_novel_manga_batch.py --input yaml --source step2-pages（ページ生成）

必要な場合だけ:
  ↓ tools/novel_prompt_ir_embed_snapshots.py（スナップショット埋め込み）
  ↓ tools/novel_prompt_ir_export_md.py（互換 Markdown）
[manga/manga_XX.md]  ← 互換出力・人間向けの副本（正本は YAML。変更は YAML→再エクスポート）
```

- 本番前は `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` を推奨。
- 通常は `--input yaml` が既定。旧 Markdown 互換だけ `--input markdown`。
- 修正は **常に YAML 側**。`manga_XX.md` が要るときだけ再エクスポート。
- **Step1 の `tag` 行（画像向けトークン列）は英語のみを載せる**: `tools/manga_prompt_ir/scene_prompt.py` が `forge_novel_manga_batch` / `novel_prompt_ir_export_md` から呼ばれ、**`composition` / `camera` / `lighting` / subject の状況語**は **`*_en` を優先**し、旧フィールドは **CJK を含まない場合のみ**タグに含める（日本語メモがタグに漏れない）。確実に載せたい語は **`focus_en`**, **`pose_action_en`**, **`expression_en`**, **`panels[].mood_atmosphere_en`** などを YAML に書く。

### 互換 Markdown を出すとき（`novel_prompt_ir_export_md.py`）

**`--manga-page` を渡す実行では、手順を一本化するため `--novelai-pipe-tags` を付ける**と、Step1 の各コマ `tag` 行が NovelAI 向け **`ベース | キャラ`** 形式になり、`forge_novel_manga_batch`（step1-panels 等）と形が揃います。付けないと Step1 がカンマ一列になりやすい。

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

画像生成バッチの具体例・`--dry-run`・provider は [index.md よく使うコマンド](index.md#よく使うコマンド) と [forge-txt2img スキル](../../.rulesync/skills/forge-txt2img/SKILL.md) を参照。

---

<span id="yaml-minimal-step1"></span>

## ページ YAML の最小構造と Step1 互換出力の元

`novels/<作品>/manga/pages/manga_XX_pYY.yaml` は **Manga Tag Mode の正本**です。`tools/novel_prompt_ir_export_md.py` が互換 `manga/manga_XX.md` を出力するとき、**`### Step1`** ブロック（各コマの説明文・翻訳・`tag:` 行の素材）は、この YAML の `panels[]`・`manga`・`scene`・`render_instruction` 等から組み立てられます。**互換 Markdown の Step1 は「ページ YAML をどう書いたか」のエクスポート結果**であり、創作技法ファイル（`_how_to/manga.md`）ではなく **本ドキュメントとスキーマ**が型の参照先になります。

- **型の正本**: `tools/manga_prompt_ir/schemas/manga_page.py`（`MangaPagePrompt`）
- **検証**: `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality`
- **スキル総説**: [manga-prompt-ir/SKILL.md](../../.rulesync/skills/manga-prompt-ir/SKILL.md)
- **画風トークン（`manga.genre_tags` / `visual_tags`）**: フルカラー生成を前提にするなら、**原則 `monochrome`・`screentone` を入れない**（`novel_prompt_ir_export_md.py` が各コマの互換 Step1 `tag` 行に連結するため）。例外・語彙の目安は創作技法 [`_how_to/manga.md`](../../_how_to/manga.md)（雛形 [`_how_to.example/manga.md`](../../_how_to.example/manga.md)）の「`manga.genre_tags` / `manga.visual_tags`」節。

以下は **`MangaPagePrompt` に沿った**最小例です（フィールド名・入れ子はスキーマが正本）。**実作品の具体例**としては同フォルダの `*.yaml` が最も手堅いです。

### 旧版サンプルから主な差分（よくハマる点）

| 旧例 | 現在のスキーマ側 |
|------|------------------|
| `manga_id` / `page_number` | ファイル名（`manga_01_p01.yaml` 等）と YAML 内の `meta` で表現。ルートに `manga_id` は無い |
| `meta.purpose` / `read_order` | `meta.intent: manga_page` と **`reading_order: right_to_left`**（または `left_to_right`）。ほかに `aspect_ratio`・`page_count` |
| `manga.style`（一文） | **`manga.genre_tags[]`**・**`visual_tags[]`** と **`panel_layout`**（画風・モノクロ／カラーはここと `color_palette`） |
| `scene.time` | **`time_of_day`**（任意）。画像用英語は **`time_of_day_en`** |
| `scene.background_tags` | `scene` には無い（背景タグ列は `manga.background_tags[]` も可）。**`background_notes`** は編集用に日本語可。**タグ行・バッチは `background_notes_en` のみ**（日本語にはフォールバックしない。欠けると `MangaPagePrompt` 検証エラー）。または **`prompt_tags`**／**`background_concepts[]`** |
| `panels[].panel_number` | **`panel_id`**（整数） |
| `subjects[].action` | **`pose_action`**。**`description`** は必須文字列（キャラでも背景オブジェクトでも） |
| `composition.camera` / `shot_type` | **`composition`** と **`camera`** は別オブジェクト。アングルは **`camera.angle`**、画角は **`camera.shot_size`** など |
| `text.dialogue[].line` | **`content`** |
| `prompt_tags` が1本の文字列 | **`prompt_tags: []` は文字列のリスト** |
| （無記載） | **`render_instruction`**（task / prompt_header / panel_policy / character_policy が実質の運用で常用） |
| （無記載） | **`scene.location_en` は必須（非空）**。`background_notes` / `time_of_day` / `weather` を書いた場合は対応する **`*_en` も必須**。背景 subject の **`description_en`** など（詳細は [manga-prompt-ir/SKILL.md](../../.rulesync/skills/manga-prompt-ir/SKILL.md)） |
| （無記載） | **`color_palette.mode`**（`monochrome` / `limited_color` / `full_color`） |
| （無記載） | **`character_snapshots[]`**（本番では embed または手書きで埋め、バッチと整合） |
| （無記載） | **`panels[].negative_tags`** / **`panels[].omit_negative_tags`**（任意・**コマ単位 txt2img** 向け。語彙は [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)「コマ別ネガ」） |

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

`--input yaml` かつ **`--source step1-panels`** のとき、各コマの `negative_prompt` は `forge_novel_manga_batch.py` 内で次の順に合成されます。

1. CLI の `--negative-prompt`（未指定時はツール既定）
2. `technical.negative_tags`
3. `panels[].omit_negative_tags` に書いた断片を、1〜2 の結果から除去
4. `panels[].negative_tags` を追加（重複除去）

**ページ生成**（`step1-pages` / `step2-pages`）ではジョブ単位のネガは主に CLI の `--negative-prompt`。上記の `technical` / `panels[]` ネガフィールドは **コマ単位生成向け**と捉える。

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
