# プロフィールタグ化
## 構造化IR優先（manga-prompt-ir）

新規のキャラクター画像タグは、まず **`manga-prompt-ir`** の `CharacterPrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/tag/characters/<character_id>.yaml`
- 人間向けの副本・既存バッチ互換: `novels/<作品>/tag/<romaji>.md`
- 互換 Markdown は `tools/image_provider_novel_tag_batch.py` 向けの抽出形式に加え、**手作業でのタグ確認・差分レビュー・可読参照**に用いる
- 中間データは作り直し可能だが、**日本語の意味・固定特徴・変更禁止・状況別タグ**は失わない

---

## バリアント2階層（000番台・100番台）

キャラクタータグは **服装スロット（000番台）** と **資料・ポーズスロット（100番台）** に分ける。100番台は000番台の衣装状態と**合成**し、三面図・紹介シート・決めポーズなど**参照画像**を作る（漫画の `variant_id` には使わない）。

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
| `danbooru_tags` に入れる | 衣装・アクセ・状況に応じた裸露タグ、固定特徴の**再掲は可** |
| **入れない** | **`standing` および一切の姿勢タグ**、シーン背景、三面図タグ、資料向け劇的ポーズ |
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

- **`|` の左**: 資料・画角・ポーズ・行為（103/104）タグ。
- **`|` の右**: `combines_with` の000番台 `danbooru_tags` を**そのまま複写**（`(character)` プレースホルダ不可）。
- エクスポート: `novel_prompt_ir_export_md.py --novelai-pipe-tags`（ツール未対応時は MD 上で `|` まで手書き）。

### 000・固定基礎（`000_base`）

衣装・姿勢・背景・表情・行為は書かない（下記チェックリスト参照）。

---

## Tag Mode チェックリスト（`tag.md` を実際のタグへ「効かせる」）

> `tag.md` はルール文書であり、画像生成ツールが自動読み込みしない。**反映＝YAML IR または互換 MD へ書き込んだ状態**。

### 1) 固定特徴（全バリアント共通）

- **固定特徴の正本**は **`000_base`** の `danbooru_tags`。000番台には再掲可（**姿勢は100番台**）。
- **固定に入れない**: 状況で変わる衣装、`standing` 等の姿勢、背景。

#### YAML IR の `costume.outfit_tags`

- **`costume.outfit_tags` は全バリアントに合成される**。衣装英語トークンは **`prompt_variants[].danbooru_tags` のみ**。
- 迷ったら **`costume.outfit_tags: []`**。

### 2) 状況バリアント（最低限）

- **先頭 `000_base`** → **000番台（服装）** → **100番台（資料）** の順。
- **000番台**の例: `001_normal`（平服）、戦闘時、水着… 作品に応じて追加。
- **100番台**（漫画 `variant_id` には使わない）: `100_intro` / `101_turnaround` / `102_signature_pose`、該当作品なら `103_show_treatment` / `104_union_vaginal`。
- 省略するときは**省略理由**を説明に残す。

#### 固定基礎バリアント（`000_base`）

| 項目 | 内容 |
|------|------|
| 見出し | `## 000. 固定基礎` |
| `variant_id` | **`000_base`** |
| 入れる | 性別・体格・髪・目・肌・種族・固定小物・キャラ名トークン |
| 入れない | 衣装、姿勢、背景、表情、nsfw、局部・行為 |

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

## 出力例（フィオナ・ストームブレイド／3桁・2階層）

一般向けサンプルキャラ。レガシー2桁例は `_how_to/tag.md` 末尾の旧例を参照。

```
フィオナ・ストームブレイド（Fiona Stormblade）

000. 固定基礎
**説明**: フィオナの固定外見のみ。15歳の熱血戦士体型。母似の顔立ち。燃えるようなオレンジ色のショートヘア、琥珀色の瞳、色白の肌。母の落書き風の狼タトゥー（腕・取り外さない）。衣装・場所・表情・ポーズは指定しない。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, fiona_stormblade

Caption:
Fiona Stormblade, a sporty young woman with orange short hair, amber eyes, fair skin, and a wolf tattoo on her arm.

和訳: オレンジのショートヘアと琥珀色の瞳、色白の肌を持つスポーティな若い女性フィオナ・ストームブレイド。腕に狼のタトゥーがある。

001. 平服（通常時）
**説明**: 普段の訓練着。タンクトップとショーツ。快活な笑顔は Caption で示すが、姿勢・訓練場の背景タグは載せない（資料が要れば100番台）。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, cheerful_expression, bright_smile, tank_top, shorts, fiona_stormblade

Caption:
Fiona Stormblade in her usual tank top and shorts, cheerful bright smile, sporty build and wolf tattoo on her arm.

和訳: いつものタンクトップとショーツに、明るい笑顔のフィオナ。スポーティな体型と腕の狼タトゥー。

002. 戦闘時
**説明**: 革の鎧と大剣の戦闘服。決意の表情はタグに含めるが、ダイナミックポーズ・戦場・立ち姿は100番台へ分離する。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, determined_expression, greatsword, leather_armor, boots, fiona_stormblade

Caption:
Fiona Stormblade in leather armor with a greatsword, determined expression, wolf tattoo visible on her arm.

和訳: 革の鎧と大剣を携えたフィオナ。決意に満ちた表情と腕の狼タトゥー。

003. 水着
**説明**: ビキニの水着衣装のみ。ビーチ・立ち・日光は載せない。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, energetic_expression, wet_hair, water_droplets, bikini, fiona_stormblade

Caption:
Fiona Stormblade in a bikini, wet orange hair and energetic expression, wolf tattoo on her arm.

和訳: ビキニ姿のフィオナ。濡れたオレンジの髪と活気ある表情、狼のタトゥー。

--- 100番台（資料）。`|` 右は **組み合わせ** の000番台タグ列を複写 ---

100. キャラクター紹介
**組み合わせ**: 001_normal
**説明**: 作品紹介用のキャラクターシート。平服で白背景。プロフィール用の文字レイアウトを許容する。

Danbooru Tags:
character sheet, reference sheet, character profile, clean white background, simple background, text, english text, high detail, masterpiece | female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, cheerful_expression, bright_smile, tank_top, shorts, fiona_stormblade

Caption:
Fiona Stormblade, character introduction sheet on white background, tank top and shorts, cheerful expression, reference layout with text elements.

和訳: 白背景の紹介シート。タンクトップとショーツの平服で、快活な表情のフィオナ。

101. 三面図
**組み合わせ**: 001_normal
**説明**: 正面・側面・背面の三面図資料。同一平服・同一プロポーションで白背景に揃える。

Danbooru Tags:
three views, front view, side view, back view, character sheet, reference sheet, same girl, clean white background, simple background, high detail, masterpiece | female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, cheerful_expression, bright_smile, tank_top, shorts, fiona_stormblade

Caption:
Fiona Stormblade, turnaround reference, front side and back views, white background, consistent tank top and shorts outfit.

和訳: フィオナの三面図。白背景で正・側・後を同一の訓練着で統一した参照資料。

102. 決めポーズ
**組み合わせ**: 001_normal
**説明**: 作品の決めポーズ資料。両手を腰に、視線はこちら。背景は白のみ。

Danbooru Tags:
decisive pose, signature pose, powerful pose, hands on hips, confident smile, looking at viewer, standing, full body, clean white background, masterpiece, best quality | female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, cheerful_expression, bright_smile, tank_top, shorts, fiona_stormblade

Caption:
Fiona Stormblade, signature pose with hands on hips, confident smile, looking at viewer, full body on white background, tank top and shorts.

和訳: 決めポーズのフィオナ。腰に手を当て、こちらを見る自信ある笑み。全身・白背景。

```

---

## 作風・画風タグ（作品共通・任意）

ファイル先頭やバッチの style 指定で、全体に共通適用するとよい例:

```
{best quality}, {very aesthetic}, {ultra-detailed}, {best illustration},
```

---

## `_how_to/tag.md` との関係

- **正本（雛形）**: 本ファイル **`_how_to.example/tag.md`**
- **ユーザー調整**: **`_how_to/tag.md`** — 作品固有の特殊ルール・長い出力例・ジャンル固有の列挙を足す
- 恒久ルールを変えるときは **本ファイルを先に更新**し、必要なら `_how_to/tag.md` に反映する
