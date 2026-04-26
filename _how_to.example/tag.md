## 構造化IR優先（manga-prompt-ir）

新規のキャラクター画像タグは、まず **`manga-prompt-ir`** の `CharacterPrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/tag/characters/<character_id>.yaml`
- 既存バッチ互換: `novels/<作品>/tag/<romaji>.md`
- 互換 Markdown は `tools/forge_novel_tag_batch.py` のための出力層として扱う
- 中間データは作り直し可能だが、**日本語の意味・固定特徴・変更禁止・状況別タグ**は失わない

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

- **セクション見出し**は次のいずれかに統一する（**番号 `N` は 1 始まり・章内で連番**）。
  - **推奨**: `## N. 短い見出し`（例: `## 1. 通常時`）。目次・差分・ツールの区切りが一番明確。
  - **互換**: 行頭が `### N.` または **`N. 見出し` だけの行**（先頭の `#` なし）も抽出対象。ただし本文中の「1. 〜」と誤認しやすいので、**新規作成では `## N.` を推奨**。
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



