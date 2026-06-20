# 挿絵 IR（illustration-prompt-ir）とツール・パイプライン

**読者**: 小説本文から挿絵・章扉・表紙を作るときの操作マニュアルです。創作技法ではなく、YAML の置き場、検証、画像保存先を扱います。

---

## 二段パイプラインの概要

挿絵・表紙の生成は **Step 1（計画 MD）→ Step 2（YAML IR）→ 画像生成** の順で進めます。

```
_meta.md §3.2 章別割当表
        ↓
Step 1: illustrations/plans/chapter_plan.md  ← 候補3点・採用・本文アンカー
        ↓（採用分のみ）
Step 2: illustrations/pages/illustration_XX_pYY.yaml  ← YAML IR
        ↓
        画像生成 → illustrations/_assets/illustration_XX/
```

- **Step 1（Illustration Plan Mode）**: チャットで「挿絵計画を作成してください」と入力します。Monogatari Coach は `_meta.md` §3.2 を読み、章ごとに候補3点・採用・本文アンカーを `illustrations/plans/chapter_plan.md` に記録します。
- **Step 2（Illustration Tag Mode）**: チャットで「挿絵 IR を作成してください」と入力します。採用が確定した章だけ `illustrations/pages/*.yaml` を作成します。

Step 1 を経ずに Step 2 だけを実行しないでください。

---

## 使う場面

- 本文中の一場面を、一枚絵として画像化したいとき
- 章頭挿絵やクライマックス絵を管理したいとき
- 表紙の構図・人物配置・余白方針を YAML として固定したいとき

**Step 1（計画）の最小指示:**

```text
挿絵計画を作成してください。
```

**Step 2（YAML IR）の最小指示:**

```text
本文から挿絵タグを作成してください。
```

対象を指定する場合:

```text
novels/NNN_作品名/_novel_text/novel_text01.md を参照して、第1章の挿絵IRを作成してください。
```

---

## 正本と保存先（三層）

| 層 | パス | 役割 |
|---|---|---|
| 方針・割当 | `novels/<作品>/_meta.md` §3〜§3.2 | 章別枚数・表紙有無の確定正本 |
| 計画（Step 1） | `novels/<作品>/illustrations/plans/chapter_plan.md` | 候補3点・採用・本文アンカー |
| 表紙計画（Step 1） | `novels/<作品>/illustrations/plans/cover_plan.md` | 表紙の計画（別枠） |
| YAML IR（Step 2） | `novels/<作品>/illustrations/pages/illustration_XX_pYY.yaml` | 画像生成用の実行正本 |
| 画像保存先 | `novels/<作品>/illustrations/_assets/illustration_XX/` | 生成された画像 |
| キャラ外見正本 | `novels/<作品>/tag/characters/<character_id>.yaml` | 衣装・固定外見 |
| 互換 Markdown | `novels/<作品>/illustrations/illustration_XX.md` | 任意の可読副本 |

表紙は `illustration_00_pYY.yaml`、章挿絵は `illustration_01_pYY.yaml` 以降を使います。番号設計は `_meta.md` §3 に書きます。

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

### ディレクトリ scaffold・計画チェック・MD export

```bash
# illustrations/plans/ と pages/、_assets/<stem>/ を用意
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# 挿絵計画 MD を必須にする（chapter_plan.md。表紙 YAML があるとき cover_plan.md も）
python tools/novel_project_check.py novels/NNN_作品名 --require-illustration-plan

# YAML IR から互換 Markdown（illustrations/illustration_XX.md）へ export
python tools/novel_prompt_ir_export_md.py \
  --output-dir novels/NNN_作品名 \
  --character novels/NNN_作品名/tag/characters/koharu.yaml \
  --illustration-page novels/NNN_作品名/illustrations/pages/illustration_01_p01.yaml \
  --novelai-pipe-tags
```

複数 `--illustration-page` を渡すと stem（`illustration_01` 等）ごとに MD を分割出力します。キャラ MD を上書きしたくないときは `--no-character-output` を付けます。

---

## YAML の考え方

挿絵IRは漫画IRと同じ `MangaPagePrompt` を使います。差分は `meta.intent: illustration` です。

`panels[]` は漫画のコマではなく、構図の構成セルです。単体挿絵は1セル、群像や複合構図では複数セルを使えます。

枠線は既定で使いません。枠を使う場合だけ、`manga.panel_layout` や `render_instruction.user_directives.page_notes` に理由を書きます。

---

## 最小 YAML

必須・推奨フィールドだけを含む最小構成です。`character_snapshots`・`background_concepts`・`technical` などは省略できます。

```yaml
schema_version: "1.0"
meta:
  intent: illustration
  aspect_ratio: "2:3"
  source_anchor: "novel_text01.md#scene-01"
render_instruction:
  task: このYAMLを、小説挿絵1枚分の作画依頼書として扱う。
  prompt_header: 本文の一場面を、漫画のコマ枠前提にしない完成イラストとして描く。
  panel_policy: panels[] は構成セル。単体ならセル1件を一枚絵として統合する。
  character_policy: character_id の固定外見・服装を反映する。
  text_policy: 画像内文字は原則入れない。
  output_policy: 枠線なし。1枚の完成挿絵として出力する。
manga:
  panel_layout: 枠線なし・一枚絵
scene:
  location_en: small bedroom at night
character_ids:
  - kazuki
panels:
  - panel_id: 1
    summary: 机に向かう主人公が、光るスマホに手を伸ばす。
    subjects:
      - character_id: kazuki
        pose_action_en: reaching toward phone
        expression_en: wary
    composition:
      framing_en: medium shot
    lighting:
      quality_en: dark room lit by phone screen
    prompt_tags:
      - phone_screen_light
color_palette:
  mode: full_color
```

よく使うオプションフィールド:

| フィールド | 用途 |
|-----------|------|
| `technical.negative_tags` | 出力に含めたくないタグ |
| `technical.resolution` | `2k` / `4k` など |
| `background_concepts[]` | 背景資料生成に使う場所・構図のメモ |
| `character_snapshots[]` | キャラ外見を YAML に埋め込む場合（`embed_snapshots.py` で自動生成） |
| `render_instruction.user_directives.page_notes` | ページ単位の指示メモ |

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

### provider 別 — どの env が効くか

| 環境変数 | Grok / OpenAI 系 | Forge | NovelAI |
|----------|------------------|-------|---------|
| `MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT` | ✅ | ✅ | ✅ |
| `MONOCRI_ILLUSTRATION_MODEL_DEFAULT` | ✅ | ✅ | ✅ |
| `MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT` | ✅（比率文字列） | ✅（preset → width/height） | ✅（preset → width/height。`config` の `novelai.aspect_ratio_presets`） |
| `MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT` | ✅ | — | **未使用** |
| `MONOCRI_MANGA_NOVELAI_REFERENCE_*` | — | — | ✅ **挿絵も漫画・タグと共用** |

NovelAI Vibe / ポーションの解決優先順位（挿絵・漫画・タグ共通）: **CLI** > 作品 `_meta.yaml` の `novelai.portions` > `.env` の `MONOCRI_MANGA_NOVELAI_REFERENCE_IMAGE_PATHS` 等。

挿絵バッチ CLI 例:

```bash
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --provider novelai \
  --novelai-portion-id default \
  --dry-run
```

`--dry-run` では `novelai_reference: N file(s) (source=…)` と、merge 後の `width×height`・`novelai_reference_images` をジョブごとに表示します。`provider=novelai` なのに `resolution` を指定した場合は warning を出します。

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
