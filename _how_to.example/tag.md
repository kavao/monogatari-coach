# プロフィールタグ化
## 構造化IR優先（manga-prompt-ir）

新規のキャラクター画像タグは、まず **`manga-prompt-ir`** の `CharacterPrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/tag/characters/<character_id>.yaml`
- 既存バッチ互換: `novels/<作品>/tag/<romaji>.md`
- 互換 Markdown は `tools/forge_novel_tag_batch.py` のための出力層として扱う
- 中間データは作り直し可能だが、**日本語の意味・固定特徴・変更禁止・状況別タグ**は失わない

---

## Tag Mode チェックリスト（`tag.md` を実際のタグへ「効かせる」）

> 注意: `tag.md` はルール文書であり、画像生成ツールが自動で読み込む設定ファイルではない。  
> **「効かせる」＝YAML IR（`tag/characters/*.yaml`）または互換 MD（`tag/*.md`）へ反映した**という意味になる。
> 以降は、その反映漏れを防ぐためのチェックリストである。

### 1) 固定特徴（全バリアント共通）

- **固定特徴**（髪・目・肌・体格・種族特徴・固定小物）を、各バリアントの `danbooru_tags` へ漏れなく入れる（または YAML 側の固定タグとして保持する）。
- **固定に入れてよい**: 髪色・目色・肌・種族特徴・固定小物（例: 星型ヘアピン）など、全状況で不変のもの。
- **固定に入れない**: 平服/水着/治療服など状況で切り替わる衣装、`standing` など姿勢、屋内/屋外/背景。
  - 理由: 固定タグはレンダリング時に全バリアントへ混入しやすく、**水着に平服が混ざる**事故が起きる。

#### YAML IR の `costume.outfit_tags`（混入事故の主因になりやすい）

構造化IR（`tag/characters/<character_id>.yaml`）では、次を必ず守る。

- **`costume.outfit_tags` は「全バリアントで常に合成される固定側」**として扱われる（実装はスキル **`manga-prompt-ir`** の `CharacterPrompt.fixed_prompt_tags()`）。そのためここに **平服・制服・水着・ベビードール・パジャマ等** を置くと、**裸体（nude）や別衣装のバリアントにも衣服タグが混ざる**。
- **衣装で状況が変わるタグは、必ず `prompt_variants[].danbooru_tags` にだけ書く**。`costume.main_outfit` は日本語メモとして残してよいが、**Danbooru 行に載せたい衣装英語トークンはバリアント側**が正本。
- **迷ったら `costume.outfit_tags: []`**（空配列）にし、衣装は各バリアントの `danbooru_tags` のみで表現する。
- **常に身につける固定小物**（例: 取り外さない指輪）だけを `outfit_tags` に置く運用は可。**状況で外すリボンや首飾り**は、外れるバリアントでは `danbooru_tags` 側にのみ書く。

**関連ツール**: `tools/forge_novel_tag_batch.py`（キャラ一括画像）、`tools/novel_prompt_ir_export_md.py`（互換 `tag/<romaji>.md` 出力）は上記の固定合成に従う。漫画側では `tools/novel_prompt_ir_embed_snapshots.py` がスナップショットを埋め込むため、IR の誤りは **キャラタグと漫画コマの両方**に波及しうる。

### 2) 状況バリアント（最低限）

- 最低でも次を用意する。また劇内で別のバリアントがある場合は追加する:
  - 通常時
  - 戦闘時
  - 水着
- 省略する場合は「この作品では発生しない」等、**省略理由を説明**に残す。

#### バリアント番号（管理用・最小）

- **互換 Markdown**（`tag/<romaji>.md`）では、状況ごとの見出しを **`## 1.` からそのファイル内で連番**にする（見出し体裁の細部は後述「Markdown ファイル形式」）。
- **YAML IR**（`tag/characters/*.yaml`）では、`prompt_variants` の**配列の並び**を、その連番と**同じ順**にする（先頭＝`## 1.` に対応）。
- **`variant_id`（推奨）**: 一覧や diff で並びが一目で分かるように、上記の **番号 `N` と同じ整数を ID の先頭に付ける**。形式は **`NN_short_slug`** とする（例: `01_normal`, `02_zengi_treatment`）。**2桁ゼロ埋め**を推奨する（10番台以降でも桁が揃う）。末尾の `short_slug` は意味のある英字でよい。**既存のみ英字 ID のファイル**は、触るタイミングで **番号付きへ付け替え**てよい。
- バリアントを増やすときは、手間が少ないのは **末尾に追加して連番の最後を増やす**こと。途中に挟む場合は、**以降の見出し番号・`variant_id` の番号部分・YAML の配列順をまとめて繰り下げ**て整合を取る。

### 3) `tag.md` の特殊ルール適用（該当キャラのみ）

- **出力の前提**:
  - まず物語タイトルを表示し、プロフィールの詳細を反映したうえで、状況に応じた写実的な描写で人物を記述する。
  - 事前に変換リストに基づいて単語を適切に変換する。
- **状況別に作る（列挙）**:
  - 通常時 / 戦闘時 / 水着 など作品で定義された状況
- **通常時→他状況への引き継ぎ**:
  - 通常時で書いたタグのうち、顔の飾りや種族特徴は他状況にも引き継ぐ。
- **水着**:
  - 男の娘には `Swimsuit bottom skirt` を加える。
- **背景・変換**:
  - `translucent` を含むタグは避け、代わりに `gleasy` に置き換える。
  - `glowing_iris` は避ける（戦闘/特異現象に寄るため）。

### 4) 互換 Markdown（`tag/<romaji>.md`）の最低限構造

- 各状況ブロックは次の順を崩さない:
  - `**説明**` → `**Danbooru Tags:**` →（次行にタグ1行）→ `**Caption:**` → `**和訳:**`
- タグ本文は **必ず1行**（カンマ区切り、行頭インデントなし）。

`tag/<romaji>.md` を直接書く場合でも、将来 YAML 化しやすいように、各状況について次を明確にする。

- `character_id`
- 日本語の状況説明
- 固定特徴（髪・目・肌・体格・種族・固定小物）
- 状況別 Danbooru Tags
- Caption
- 和訳

登場人物を描画ＡＩに依頼するための補助ツールです。
ひとまず、物語のタイトルについて表示を出してから、最初にプロフィールの詳細を反映し、状況に応じた写実的な描写で人物の描写をしてください
事前に変換リストに基づいて単語を適切に変換してください。
登場人物について、それぞれ指定された状況（通常時、戦闘義、水着、別途定義されている物がある場合はそれを出す）ごとに作成してください。
通常時で書いたタグのうち顔に付ける飾りや、種族に属するものは、他の状況にも引き継いでください。
glowing_irisが含まれるタグについては、目が輝くというのは戦闘時や、モンスターなどの特異な現象が多いため、光源があるように輝かせないようにしてください。
シーンの格好の再現も出来れば行うと好ましいです
タグやcaptionには必ずそれぞれ英語で登場人物の名前を入れてください。
タグ出力は全員もお願いします。メッセージが足りない場合には分割で構いません

まず日本語での説明を書きます。
続いて、stable diffusionやnovelAIに渡す種類の形のタグをコンマ(,)区切りで作成してください。
画像AIで生成する時のcaptionを英語で書いてください。和訳の説明も添えます

## Markdown ファイル形式（`tag/<romaji>.md`・機械抽出と整合）

作品フォルダに **`novels/<作品>/tag/<romaji>.md`** として保存するときは、人間が読みやすいことに加え、**`tools/forge_novel_tag_batch.py`（Forge 一括 txt2img）** が安定して **Danbooru 行を取り出せる**形に揃える。ブレると一括でスキップされたり、意図しないブロック分割になる。

### ファイル先頭

- **レベル1見出し**を1行（例: `# 白峰 ゆい（Yui Shiramine）`）。
- 任意で画風メモ・`---` による区切りを置いてよい。

### 状況ブロック（1キャラあたり複数）

- **セクション見出し**は次のいずれかに統一する（**番号 `N` は 1 始まり・当該キャラの `tag/<romaji>.md` 内で連番**）。
  - **推奨**: `## N. 短い見出し`（例: `## 1. 通常時`）。目次・差分・ツールの区切りが一番明確。
  - **互換**: 行頭が `### N.` または **`N. 見出し` だけの行**（先頭の `#` なし）も抽出対象。ただし本文中の「1. 〜」と誤認しやすいので、**新規作成では `## N.` を推奨**。
  - **YAML との対応**: `tag/characters/<character_id>.yaml` の `prompt_variants` は、**この `N` の並びと同じ順**に並べる（上記「バリアント番号（管理用・最小）」）。
- **ブロック内の並び**（この順を推奨）:
  1. `**説明**: …`
  2. 空行
  3. **Danbooru ラベル行**（次項）
  4. **タグ本文**（次行・**1行**・カンマ区切り。行頭にスペースやタブを付けない）
  5. 空行
  6. `**Caption:**` と英語キャプション（**1行推奨**）
  7. 空行
  8. `**和訳:**` と日本語（ラベル表記は `**和訳:**` に揃える）

### `Danbooru Tags` 行（一括抽出の要）

- **ラベル行**は次の形にする（Markdown の太字として **`:` の位置が一定**になるようにする）。
  - 例: `**Danbooru Tags:**`（行全体が `**` で囲まれた「Danbooru Tags:」）
- **タグ本文は必ず次の行**に書く。同じ行に続けて書かない。
- **タグ本文は1行にまとめる**（複数行に分けると一括は先頭行のみ使用）。
- ラベルを `Danbooru Tags` 以外の表記に変えない（スクリプトは `Danbooru Tags` を識別子として検索する）。

### 検証コマンド（執筆後）

リポジトリルートで、対象作品パスを渡して **ドライラン**する。ジョブ数と `prompt` 先頭が表示されれば抽出OK。

```bash
python tools/forge_novel_tag_batch.py novels/<作品フォルダ名> --dry-run
```

詳細な運用はスキル **`novel-tag-md-format`**（`.rulesync/skills/novel-tag-md-format/SKILL.md`）および **`forge-txt2img`** を参照。

出力例となります
```
フィオナ・ストームブレイド（Fiona Stormblade）
1. 通常時
説明: フィオナの普段の姿。15歳の熱血戦士で、母似の快活な顔立ち。燃えるようなオレンジ色のショートヘアが風を切り、琥珀色の瞳が好奇心で輝く。筋肉質の体に狼の刺青風タトゥー（母の落書き）を付け、ポジティブな笑顔。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, cheerful_expression, bright_smile, tank_top, shorts, standing, training_ground, warm_lighting, fiona_stormblade

Caption:
A sporty young woman with windswept orange short hair and curious amber eyes, wearing a tank top and shorts with a wolf tattoo on her arm, stands cheerfully on a training ground with a bright smile.

和訳: 風を切る燃えるようなオレンジ色のショートヘアと好奇心に満ちた琥珀色の瞳を持つスポーティな若い女性が、タンクトップとショーツを着け、腕に狼のタトゥーを付け、訓練場で明るい笑顔を浮かべて立っています。

2. 戦闘時
説明: フィオナが戦闘に臨む姿。豪剣を振り、筋肉質の体が力強く動き、オレンジ色のショートヘアが激しく乱れる。琥珀色の瞳が燃え、狼のタトゥーが汗で光り、不屈の精神で突進するポーズ。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, determined_expression, sweat, dynamic_pose, greatsword, leather_armor, boots, standing, battlefield, dramatic_lighting, fiona_stormblade

Caption:
A sporty young woman with disheveled orange short hair and burning amber eyes charges with a greatsword in leather armor, standing dynamically on a battlefield, sweat highlighting her wolf tattoo.

和訳: 乱れたオレンジ色のショートヘアと燃える琥珀色の瞳を持つスポーティな若い女性が、革の鎧を纏い大剣を振り、戦場でダイナミックに突進します。汗が狼のタトゥーを光らせています。

3. 水着
説明: フィオナが水着姿で遊ぶ場面。筋肉質のスポーティな体がビキニで強調され、オレンジ色のショートヘアが水で跳ね、琥珀色の瞳が輝く。狼のタトゥーが日光に映え、ハイテンションな笑顔。

Danbooru Tags:
female, young_woman, athletic_build, sporty, orange_short_hair, amber_eyes, fair_skin, wolf_tattoo_on_arm, energetic_expression, wet_hair, water_droplets, bikini, standing, beach, sunlight, fiona_stormblade

Caption:
A sporty young woman with splashed orange short hair and sparkling amber eyes wears a bikini on a sunny beach, standing energetically with water droplets accenting her wolf tattoo.

和訳: 水しぶきのかかったオレンジ色のショートヘアと輝く琥珀色の瞳を持つスポーティな若い女性が、ビキニを着て陽光のビーチでエネルギッシュに立っています。水滴が狼のタトゥーを強調します。
```

次に、作風、画風タグについて、全体で共通で適用するとよい物を挙げます。



