# 挿絵 IR（illustration-prompt-ir）とツール・パイプライン

**読者**: 小説本文から挿絵・章扉・表紙を作るときの操作マニュアルです。創作技法ではなく、YAML の置き場、検証、画像保存先を扱います。

---

## 使う場面

- 本文中の一場面を、一枚絵として画像化したいとき
- 章頭挿絵やクライマックス絵を管理したいとき
- 表紙の構図・人物配置・余白方針を YAML として固定したいとき

チャットへの最小指示:

```text
本文から挿絵タグを作成してください。
```

対象を指定する場合:

```text
novels/NNN_作品名/_novel_text/novel_text01.md を参照して、第1章の挿絵IRを作成してください。
```

---

## 正本と保存先

| 役割 | パス |
|------|------|
| 挿絵 YAML 正本 | `novels/<作品>/illustrations/pages/illustration_XX_pYY.yaml` |
| スキーマ | `tools/manga_prompt_ir/schemas/manga_page.py` |
| 画像保存先 | `novels/<作品>/illustrations/_assets/illustration_XX/` |
| キャラ外見正本 | `novels/<作品>/tag/characters/<character_id>.yaml` |
| 互換 Markdown | `novels/<作品>/illustrations/illustration_XX.md`（任意） |

表紙は `illustration_00_p01.yaml`、章挿絵は `illustration_01_p01.yaml` 以降にする運用が扱いやすいです。厳密な番号設計は作品の `_meta.md` に書きます。

---

## YAML の考え方

挿絵IRは漫画IRと同じ `MangaPagePrompt` を使います。差分は `meta.intent: illustration` です。

`panels[]` は漫画のコマではなく、構図の構成セルです。単体挿絵は1セル、群像や複合構図では複数セルを使えます。

枠線は既定で使いません。枠を使う場合だけ、`manga.panel_layout` や `render_instruction.user_directives.page_notes` に理由を書きます。

---

## 最小 YAML

```yaml
schema_version: "1.0"
meta:
  intent: illustration
  aspect_ratio: "2:3"
  page_count: 1
  source_anchor: "novel_text01.md#scene-01"
  illustration_type: "chapter_illustration"
render_instruction:
  task: このYAMLを、小説挿絵1枚分の作画依頼書として扱う。
  prompt_header: 本文の一場面を、漫画のコマ枠前提にしない完成イラストとして描く。
  panel_policy: panels[] は構成セル。単体ならセル1件を一枚絵として統合する。
  character_policy: character_snapshots または character_id の固定外見・服装・禁止事項を反映する。
  text_policy: 画像内文字は原則入れない。
  output_policy: 1枚の完成挿絵として出力する。枠線は既定なし。
  user_directives:
    page_notes:
      - 枠線なし。漫画ページではなく一枚絵として扱う。
    defaults:
      required_prompt_tags: []
      omit_prompt_tags:
        - comic panel
        - panel borders
manga:
  genre_tags:
    - illustration
  visual_tags:
    - anime illustration
    - detailed background
  panel_layout: 枠線なし・一枚絵・セル境界の黒枠なし
scene:
  location: 深夜の自室
  location_en: small bedroom at night
character_ids:
  - kazuki
character_snapshots: []
background_concepts: []
panels:
  - panel_id: 1
    summary: 机に向かう主人公が、光るスマホに手を伸ばす。
    subjects:
      - character_id: kazuki
        description: 机に向かう主人公
        description_en: protagonist at desk
        pose_action: スマホに手を伸ばす
        pose_action_en: reaching toward phone
        expression: 警戒している
        expression_en: wary
    composition:
      framing_en: medium shot
      focus_en: lit smartphone on desk
    camera:
      shot_size_en: medium shot
    lighting:
      quality_en: dark room lit by phone screen
    text:
      dialogue: []
      narration: []
      monologue: []
      sfx: []
    mood_atmosphere_en:
      - quiet tension
    prompt_tags:
      - phone_screen_light
color_palette:
  mode: full_color
technical:
  resolution: 2k
  quality_level: high
  negative_tags:
    - bad anatomy
    - comic panel borders
    - split screen
```

---

## 検証

作品フォルダ全体を確認します。

```bash
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality
```

個別ファイルだけ確認する場合:

```bash
python tools/novel_prompt_ir_validate.py \
  --character novels/NNN_作品名/tag/characters/kazuki.yaml \
  --illustration-page novels/NNN_作品名/illustrations/pages/illustration_01_p01.yaml
```

---

## 画像保存先

`tools/novel_image_layout.py` で保存先を作成・確認できます。

```bash
python tools/novel_image_layout.py scaffold novels/NNN_作品名 -v
python tools/novel_image_layout.py paths novels/NNN_作品名
```

`illustrations/pages/illustration_01_p01.yaml` がある場合、保存先は次になります。

```text
novels/<作品>/illustrations/_assets/illustration_01/
```

画像生成は必ず dry-run で内容を確認してから本番へ進みます。

---

## 画像生成バッチ

挿絵YAMLから生成ジョブを作る入口です。まず dry-run でプロンプトと保存先を確認します。

```bash
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 --dry-run
```

CLI を省略した場合は `.env` の挿絵用既定値を使います。

```dotenv
MONOCRI_ENV_VERSION=2026-05-16
MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT=grok_pro
MONOCRI_ILLUSTRATION_MODEL_DEFAULT=
MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT=book_cover
MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT=2k
```

優先順位は CLI `--provider` / `--model` / `--aspect-ratio` / `--resolution` > `.env` の `MONOCRI_ILLUSTRATION_*` > ツール既定です。`MONOCRI_ILLUSTRATION_MODEL_DEFAULT` が空なら provider 側の `default_model` を使います。

Grok / OpenAI / OpenRouter 系では、挿絵YAMLを `natural_sections` formatter で自然文セクションへ変換します。`technical.negative_tags` や CLI の negative は `Do not include:` に移し、API の `negative_prompt` には渡しません。Forge / NovelAI は従来互換の `tag_csv` を使います。

formatter を比較するときは `--prompt-formatter` を使います。

系列を絞る場合:

```bash
python tools/image_provider_novel_illustration_batch.py \
  novels/NNN_作品名 \
  --illustration-stem illustration_01 \
  --provider grok_pro \
  --prompt-formatter natural_sections \
  --model quality \
  --aspect-ratio book_cover \
  --resolution 2k \
  --dry-run
```

本番生成は、dry-run の内容を確認してから `--dry-run` を外して実行します。
