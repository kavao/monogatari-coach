# プロフィールタグ化
## 構造化IR優先（manga-prompt-ir）

新規のキャラクター画像タグは、まず **`manga-prompt-ir`** の `CharacterPrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/tag/characters/<character_id>.yaml`
- 人間向けの副本・既存バッチ互換: `novels/<作品>/tag/<romaji>.md`
- 互換 Markdown は `tools/image_provider_novel_tag_batch.py` 向けの抽出形式に加え、**手作業でのタグ確認・差分レビュー・可読参照**に用いる
- 中間データは作り直し可能だが、**日本語の意味・固定特徴・変更禁止・状況別タグ**は失わない

---

## バリアント2階層（000番台・100番台）と身体的正本（3階層継承）

キャラクタータグは **服装スロット（000番台）** と **資料・ポーズスロット（100番台）** に分ける。100番台は000番台の衣装状態と**合成**し、三面図・紹介シート・決めポーズなど**参照画像**を作る（漫画の `variant_id` には使わない）。

**露出事故防止**のため、タグの注入経路は **concepts.md「Tag Mode 身体的正本（3階層継承）」** に従い、次も守る。

| 階層 | スロット | 代表 `variant_id` | 用途 |
|------|----------|-------------------|------|
| Level 1 | 固定外見（SFW） | `000_base` | 髪・目・肌・種族・固定小物。**露出・性器タグ禁止**。 |
| Level 2 | 身体的正本（NSFW） | **`006_nude`** | `nude`, `uncensored`, 性器・秘部詳細の**唯一の正本**（NSFW 作品のみ） |
| Level 3 | 状況 | `007_arousal` 等 | **`combines_with: 006_nude` 必須**。表情・体液・行為タグのみを載せ、身体詳細は継承 |

**固定合成経路**（`appearance.distinctive_features`, `manga_rules.consistency_tags`）にも **裸限定タグを置かない**。

- **漫画 batch の主経路**（`subjects[].variant_id` 指定時）: `tools/image_provider_novel_manga_batch.character_ir_tags()` は **`000_base` + 当該バリアント + `combines_with` のみ**を合成する（**`distinctive_features` / `consistency_tags` は混ぜない**）。
- **副経路**（variant 未指定、`novel_prompt_ir_embed_snapshots` の `fixed_tags`、`prompt_renderer` 等）: 上記フィールドを**状況に関係なく合成し得る**。裸限定タグが残っていると**着衣コマにも漏れる**。

身体詳細の Danbooru 正本は **`006_nude` のみ**。Level 1 から裸限定タグを除外する（`novel_prompt_ir_validate.py` で検出可）。

| 帯 | `variant_id` 先頭 | 用途 | 漫画 `subjects[].variant_id` |
|----|-------------------|------|------------------------------|
| **000** | `000_base` | 固定外見のみ（衣装・ポーズ・背景なし） | 使わない |
| **000番台** | `001_` … `099_` | **服装・衣装状態**（平服・戦闘服・水着 等） | **使う** |
| **100番台** | `100_` … `199_` | **資料用**（紹介・三面図・ポーズ・該当作品の治療/結合資料等） | **使わない** |

### 番号・見出し・`variant_id`（3桁固定）

- **形式**: **`NNN_short_slug`**（3桁ゼロ埋め＋英字スラッグ）。例: `000_base`, `001_normal`, `100_intro`, `101_turnaround`。
- **互換 Markdown** の見出しは **`## NNN. 短い見出し`** とし、**`NNN` ＝ `variant_id` 先頭3桁**に揃える。
- **YAML IR** の `prompt_variants` 配列順は見出しの**数値昇順**（`000` → `001` → … → `100` → `101`）。
- **レガシー2桁**（`00_base`, `01_normal`）は移行まで有効。触るタイミングで3桁へ揃える。

### 000番台（服装スロット）

| 項目 | 内容 |
|------|------|
| 代表例 | `001_normal` ＝ **平服**（作品の通常時衣装） |
| `danbooru_tags` に入れる | **衣装・アクセ・半脱衣装**（例: `bra_visible`, `clothing_aside`）、固定特徴の**再掲は可** |
| **入れない** | **`standing` および一切の姿勢タグ**、シーン背景、三面図タグ、資料向け劇的ポーズ、**`nude` / 性器・秘部タグ**（→ **`006_nude` へ**） |
| 背景 | **原則なし**（単色背景が要る場合は100番台へ） |

- **漫画**: `subjects[].variant_id` は **000番台のみ**。構図・表情・ポーズ・場所は `panels[].prompt_tags` で上乗せする。

### 100番台（資料・ポーズスロット）

| 標準ID | 見出し例 | 内容 |
|--------|----------|------|
| **`100_intro`** | キャラクター紹介 | 紹介用シート（文字要素あり可） |
| **`101_turnaround`** | 三面図 | 正・側・後を**1バリアントに集約** |
| **`102_signature_pose`** | 決めポーズ | 作品の「顔となる」ポーズ |

| 項目 | 内容 |
|------|------|
| **`combines_with`** | 平服資料は **`001_normal`**。 ほか衣装状態に合う000番台 |
| 各ブロック | **`説明`・`組み合わせ`・`Caption`・`和訳` を必ず書く** |
| 入れない | 衣装・裸露状態の差し替え（000番台へ）、治療室・ベッド等の**シーン背景** |

#### 100番台の NovelAI パイプ区切り

```text
（100番台の資料・構図タグ） | （組み合わせ先000番台のタグ列）
```

- **`|` の左**: 資料・画角・ポーズタグ（カスタムの局部・行為は作品 YAML のみ）。
- **`|` の右**: `combines_with` の000番台 `danbooru_tags` を**そのまま複写**（`(character)` プレースホルダ不可）。
- エクスポート: `novel_prompt_ir_export_md.py --novelai-pipe-tags`（ツール未対応時は MD 上で `|` まで手書き）。

### 006・身体的正本（`006_nude`）

| 項目 | 内容 |
|------|------|
| 見出し | `## 006. 服を外したとき` 等 |
| `variant_id` | **`006_nude`**（作品で別 ID にしてもよいが、Level 3 の `combines_with` と揃える） |
| 入れる | `nude`, `uncensored`, 性器・秘部・裸で初めて見える身体的詳細 |
| 入れない | 衣装、資料向けポーズ、シーン背景 |
| 必須条件 | **NSFW を扱う作品**で Tag Mode 時に作成。全年齢作品は省略可（理由を残す） |

- **Level 3**（`007_arousal`, `008_relax`, `103_*`, `104_*` 等）は **`combines_with: 006_nude`** を付け、身体詳細を再掲しない。

### 000・固定基礎（`000_base`）

衣装・姿勢・背景・表情・行為は書かない（下記チェックリスト参照）。

#### `solo` の置き場（継承と矛盾しない）

`000_base` の `danbooru_tags` は **キャラ画像バッチ・漫画 batch の両方で全バリアントに継承**される。`solo` を `000_base` に入れると、`combines_with` 付きの結合資料（`104_*` 等）や `1boy` / `2girls` など複数人を想定するタグと矛盾する。

| 置く場所 | `solo` |
|----------|--------|
| **`000_base`**（継承用） | **載せない**（`1girl` / `1boy` のみ） |
| **ソロ資料バリアント**（`100_intro` / `102_signature_pose` 等） | **そのバリアントの `danbooru_tags` に書く** |
| **生成実行のみ** | `--prepend-tags solo` + `--variant-id` で対象ジョブを絞る |

横断正本: **`.rulesync/rules/concepts.md`**「Tag Mode バリアント階層」。

---

## Tag Mode チェックリスト（`tag.md` を実際のタグへ「効かせる」）

> `tag.md` はルール文書であり、画像生成ツールが自動読み込みしない。**反映＝YAML IR または互換 MD へ書き込んだ状態**。

### 1) 固定特徴（全バリアント共通）

- **固定特徴の正本**は **`000_base`** の `danbooru_tags`。000番台には再掲可（**姿勢は100番台**）。
- **固定に入れない**: 状況で変わる衣装、`standing` 等の姿勢、背景、**露出・性器・裸限定タグ**、**`solo`（人数固定。ソロ資料バリアントへ）**。
- **`appearance.distinctive_features` / `manga_rules.consistency_tags`** にも **裸限定タグを置かない**（主経路は `000_base` 優先だが、副経路で合成され得る。上記「固定合成経路」参照）。

#### YAML IR の `costume.outfit_tags`

- **`costume.outfit_tags` は全バリアントに合成される**。衣装英語トークンは **`prompt_variants[].danbooru_tags` のみ**。
- 迷ったら **`costume.outfit_tags: []`**。

### 2) 状況バリアント（最低限）

- **先頭 `000_base`** → **000番台（着衣・半脱衣装）** → **`006_nude`（NSFW 作品）** → **100番台（資料）** の順。
- **000番台**の例: `001_normal`（平服）、戦闘時、水着… 作品に応じて追加。
- **100番台（汎用）**: `100_intro` / `101_turnaround` / `102_signature_pose`。
- **カスタム要素**（治療・接触資料等）は **`_meta.md` §6** で列挙したときのみ（付録「カスタム要素」参照）。
- 省略するときは**省略理由**を説明に残す（**テンプレート一式モード**のときは下記）。

### 3) Tag Mode テンプレート一式（指示で裁量を抑える）

**トリガー**: 「テンプレート分はすべて作成」「標準テンプレート一式」「tag テンプレ完備」、または作品 `_meta.md` §6 が **`テンプレート一式`**。

**意味**: 本ファイルおよび **concepts.md**「Tag Mode テンプレート一式」の汎用 ID は、エージェントが「不要」と判断して省略しない。ジャンル固有 ID は **`_meta.md` §6** または **`_how_to/tag.md`** の拡張テンプレを §6 に展開してから作る。

| 帯 | テンプレート一式で必ず作る ID | 追加条件 |
|----|------------------------------|----------|
| 固定 | `000_base` | 常に |
| 100番 | `100_intro`, `101_turnaround`, `102_signature_pose` | 常に（`combines_with`: 平服資料は `001_normal`） |
| 000番 | `_meta.md` §4（漫画 variant 表）に載る **すべての `variant_id`** | キャラごとに YAML に存在させる |
| **拡張** | `_meta.md` §6「カスタム要素」に列挙した ID | §6 に書いた分はすべて作る（詳細例は `_how_to/tag.md`） |

**完了前チェック（主要キャラ）**: 上表の ID が `prompt_variants` に揃っているか。100番は `description`・`combines_with`・（互換 MD では）`| ` 右の000番タグ列まで。

横断正本: **`.rulesync/rules/concepts.md`**「Tag Mode テンプレート一式」。

### 4) カスタム要素（作品・ユーザー領域）

汎用テンプレと別に、作品設定やユーザー調整に応じて追加する `variant_id`。共有ルールでは作品固有の固定IDを必須にしない。正本は **`_meta.md` §6「カスタム要素」** と作品 YAML。抽象スロット例: 資料ポーズ（100番）、関係性を示すポーズ（100番）、特殊衣装（000番）。`103_*` / `104_*` は他作品へのコピー用必須IDではない。

#### 固定基礎バリアント（`000_base`）

| 項目 | 内容 |
|------|------|
| 見出し | `## 000. 固定基礎` |
| `variant_id` | **`000_base`** |
| 入れる | 性別（`1girl` / `1boy` 等）・体格・髪・目・肌・種族・固定小物・キャラ名トークン |
| 入れない | **`solo`**（継承用 `000_base` には載せず、ソロ資料バリアントのみ）、衣装、姿勢、背景、表情、nsfw、局部・行為、**`distinctive_features` への裸限定タグ** |

- **漫画**: `variant_id` は000番台。TPO 表は **`_how_to.example/manga.md`**（ユーザー領域は `_how_to/manga.md`）。

#### バリアント番号（管理用）

- 000番台・100番台は**末尾追加**が基本。途中挿入時は見出し・ID・YAML 配列を**一括繰り下げ**。

### 4) 互換 Markdown の最低限構造

- 順序: `**説明**` → `**Danbooru Tags:**` → タグ1行 → `**Caption:**` → `**和訳:**`
- **100番台**は先頭に `**組み合わせ**: 001_normal`等を推奨。

---

## 執筆依頼文（チャット用の要約）

登場人物を描画AI向けにタグ化する。物語タイトルを示したうえ、プロフィールを反映する。

- 状況ごとに **説明 → Danbooru Tags（1行）→ Caption（英語）→ 和訳**。
- タグ・Caption に**英語のキャラ名**を入れる。
- **000番台**は衣装のみ（姿勢・背景なし）。**100番台**は資料用で `資料タグ | 000番台タグ` のパイプ形式。
- キャラ全員分。長いときは分割可。

---

## Markdown ファイル形式（`tag/<romaji>.md`）

`tools/image_provider_novel_tag_batch.py` が **Danbooru 行**を安定抽出できる形に揃える。

### ファイル先頭

- `# キャラ名（英語名）` を1行。任意で画風メモ・`---`。

### 状況ブロック

- 見出し: **`## NNN.`**（`NNN` ＝ `variant_id` 先頭3桁、数値昇順）。
- **100番台**: `**組み合わせ**:` 行を推奨。Danbooru は **`資料タグ | 000番台タグ列`**。

### `Danbooru Tags` 行

- ラベル: `**Danbooru Tags:**`（次行にタグ本文・**1行**）。
- **NovelAI パイプ**:
  - **000番台（服装のみ）**: パイプなしでキャラタグのみが基本。
  - **100番台**: **`資料タグ | combines_with の000番台タグ列`**。

### 検証

```bash
python tools/image_provider_novel_tag_batch.py novels/<作品フォルダ名> --dry-run
python tools/novel_prompt_ir_export_md.py --character novels/<作品>/tag/characters/<id>.yaml --output-dir tools_temp/ir_export_sample --novelai-pipe-tags
```

詳細: スキル **`novel-tag-md-format`**、**`image-provider`**。

---

## 出力例（フィオナ・ストームブレイド／3階層 IR・全年齢）

一般向けサンプルキャラ（NSFW なし）。**正本は YAML IR**、下記 MD はエクスポート体裁の抜粋。NSFW 作品の具体例（`006_nude` / `combines_with`）は **`_how_to/tag.md`** の藤堂優奈サンプルを参照。

### YAML IR 抜粋（`tag/characters/fiona.yaml`）

```yaml
schema_version: "1.0"
character_id: fiona
name: フィオナ・ストームブレイド
name_en: Fiona Stormblade
role: 主人公、熱血戦士
appearance:
  age_range: mid teens (15)
  body_type: athletic, sporty
  hair_style: short hair
  hair_color: orange hair
  eye_color: amber eyes
  skin_tone: fair skin
  distinctive_features: ["wolf tattoo on arm"]
prompt_variants:
  - variant_id: "000_base"
    title: "固定基礎"
    description: "固定外見のみ。狼タトゥーは常時。"
    danbooru_tags: ["1girl", "female", "young_woman", "athletic_build", "sporty", "orange_short_hair", "amber_eyes", "fair_skin", "wolf_tattoo_on_arm", "fiona_stormblade"]
  - variant_id: "001_normal"
    title: "平服（通常時）"
    danbooru_tags: ["cheerful_expression", "bright_smile", "tank_top", "shorts"]
  - variant_id: "002_combat"
    title: "戦闘時"
    danbooru_tags: ["determined_expression", "greatsword", "leather_armor", "boots"]
  - variant_id: "003_swimsuit"
    title: "水着"
    danbooru_tags: ["energetic_expression", "wet_hair", "water_droplets", "bikini"]
  - variant_id: "100_intro"
    title: "キャラクター紹介"
    combines_with: "001_normal"
    danbooru_tags: ["solo", "character_sheet", "reference_sheet", "character_profile", "clean_white_background", "simple_background", "text", "english_text", "high_detail"]
  - variant_id: "101_turnaround"
    title: "三面図"
    combines_with: "001_normal"
    danbooru_tags: ["three_views", "front_view", "side_view", "back_view", "character_sheet", "reference_sheet", "clean_white_background", "simple_background"]
  - variant_id: "102_signature_pose"
    title: "決めポーズ"
    combines_with: "001_normal"
    danbooru_tags: ["solo", "decisive_pose", "signature_pose", "hands_on_hips", "confident_smile", "looking_at_viewer", "standing", "full_body", "clean_white_background"]
```

### 互換 MD 出力例（エクスポート後）

```
# フィオナ・ストームブレイド（Fiona Stormblade）

## 構造化IR由来メモ
- character_id: `fiona`
- 固定特徴（000_base 正本）: 1girl, female, young_woman, …（**`solo` は含めない**）
- バッチ合成: 000〜099 は 000_base + 状況タグ。100番台は 資料タグ | combines_with（000_base+結合先）。**`solo` はソロ資料バリアント（例: 100_intro, 102_signature_pose）の資料タグ側のみ**

## 0. 固定基礎
**説明**: 固定外見のみ。15歳の熱血戦士体型。狼タトゥー（腕・取り外さない）。衣装・姿勢・背景は載せない。

**Danbooru Tags:**
1girl, female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, fiona_stormblade

**Caption:**
Fiona Stormblade, a sporty young woman with orange short hair, amber eyes, fair skin, and a wolf tattoo on her arm.

**和訳:**
オレンジのショートヘアと琥珀色の瞳、色白の肌を持つスポーティな若い女性フィオナ・ストームブレイド。腕に狼のタトゥーがある。

## 1. 平服（通常時）
**説明**: 訓練着（タンクトップ・ショーツ）。姿勢・訓練場背景は100番台または漫画コマ側へ。

**Danbooru Tags:**
cheerful_expression, bright_smile, tank_top, shorts

**Caption:**
Fiona Stormblade in her usual tank top and shorts, cheerful bright smile.

**和訳:**
いつものタンクトップとショーツに、明るい笑顔のフィオナ。

## 2. 戦闘時
**説明**: 革鎧と大剣。ダイナミックポーズ・戦場は100番台へ。

**Danbooru Tags:**
determined_expression, greatsword, leather_armor, boots

**Caption:**
Fiona Stormblade in leather armor with a greatsword, determined expression.

**和訳:**
革の鎧と大剣を携えたフィオナ。決意に満ちた表情。

## 3. 水着
**説明**: ビキニ衣装のみ。ビーチ・立ちは載せない。

**Danbooru Tags:**
energetic_expression, wet_hair, water_droplets, bikini

**Caption:**
Fiona Stormblade in a bikini, wet orange hair and energetic expression.

**和訳:**
ビキニ姿のフィオナ。濡れたオレンジの髪と活気ある表情。

--- 100番台（資料）。`|` 右は **`000_base` + `combines_with` 先（000番台）** ---

## 100. キャラクター紹介
**組み合わせ**: `001_normal`
**説明**: 平服の紹介シート。白背景。文字要素あり可。

**Danbooru Tags:**
character_sheet, reference_sheet, character_profile, clean_white_background, simple_background, text, english_text, high_detail, solo | 1girl, female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, fiona_stormblade, cheerful_expression, bright_smile, tank_top, shorts

**Caption:**
Fiona Stormblade, character introduction sheet on white background, tank top and shorts, cheerful expression.

**和訳:**
白背景の紹介シート。平服のフィオナ。

## 101. 三面図
**組み合わせ**: `001_normal`
**説明**: 正面・側面・背面の三面図（平服）。

**Danbooru Tags:**
three_views, front_view, side_view, back_view, character_sheet, reference_sheet, clean_white_background, simple_background | 1girl, female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, fiona_stormblade, cheerful_expression, bright_smile, tank_top, shorts

**Caption:**
Fiona Stormblade turnaround reference, front side and back views, same tank top and shorts outfit.

**和訳:**
平服の三面図参照。

## 102. 決めポーズ
**組み合わせ**: `001_normal`
**説明**: 決めポーズ資料。姿勢タグは100番台側に置く。

**Danbooru Tags:**
decisive_pose, signature_pose, hands_on_hips, confident_smile, looking_at_viewer, standing, full_body, clean_white_background, solo | 1girl, female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, fiona_stormblade, cheerful_expression, bright_smile, tank_top, shorts

**Caption:**
Fiona Stormblade, signature pose with hands on hips, confident smile, full body on white background.

**和訳:**
腰に手を当て、自信ある笑みの決めポーズ。全身・白背景。

```

---

## 作風・画風タグ（作品共通・任意）

ファイル先頭やバッチの style 指定で、全体に共通適用するとよい例:

```
{best quality}, {very aesthetic}, {ultra-detailed}, {best illustration},
```

---

## `_how_to/tag.md` との関係

- **正本（雛形）**: 本ファイル **`_how_to.example/tag.md`** — 全年齢のフィオナ例（YAML IR + 互換 MD）
- **ユーザー調整**: **`_how_to/tag.md`** — ジャンル固有の拡張テンプレや作品固有の IR サンプルを足す
- 恒久ルールを変えるときは **本ファイルを先に更新**し、必要なら `_how_to/tag.md` に反映する
