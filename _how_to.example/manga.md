## このファイルの役割（仕分け）

**創作技法の正本**として、ページ YAML をどう設計するか（誰が・どこで・POV・variant・タグ注入の優先）を扱います。

| どこに何を置くか | 内容 |
|------------------|------|
| ルート [`readme.md`](../../readme.md) | 最短入口。**漫画 IR の手順本文は載せない**。`docs/` へのリンクのみ。 |
| [`docs/image-generation/manga-prompt-ir.md`](../docs/image-generation/manga-prompt-ir.md) | **ツール・パイプライン**に加え、**ページ YAML の型・旧差分表・最小例**（互換 Step1 の元データの説明。アンカー [`#yaml-minimal-step1`](../docs/image-generation/manga-prompt-ir.md#yaml-minimal-step1)）。 |
| [`docs/image-generation/manga-tag-generation.md`](../docs/image-generation/manga-tag-generation.md) | **漫画タグ生成用**：互換 Step1/Step2 の長文テンプレ・実例・レイアウト記述・生成モード別の運用メモ。 |
| [`manga_tag.md`](manga_tag.md)（本フォルダ） | **英語タグの語彙・置換・追加ルール**（Step1／`prompt_tags` 中心）。 |
| [`manga_tag_step2.md`](manga_tag_step2.md)（本フォルダ） | **Step2**（`step2_summary`・ページ生成・抽象レイアウト）の**言い換え表・チェックリスト**。※過去に **`manga.md` にあったのではなく** `docs` 側にあった Step2 作法をここへ集約した。 |

---

## 構造化IR優先（manga-prompt-ir）

新規の漫画ページ・漫画コマは、まず **`manga-prompt-ir`** の `MangaPagePrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/manga/pages/manga_XX_pYY.yaml`
- 画像生成バッチ入力: `tools/forge_novel_manga_batch.py --input yaml`（既定。`manga/pages/*.yaml` を必須入力として読む）
- 既存Markdown互換: `novels/<作品>/manga/manga_XX.md`
- `manga_XX.md` は古い運用・外部確認・Markdown互換が必要な場合の出力層として扱う
- 中間データは作り直し可能だが、**誰が・どこで・何をし・誰に話し・どのコマがどんな役割か**は失わない

**Manga Tag Mode の初手は YAML IR 作成です。**
`manga/manga_XX.md` を直接新規作成して正本にしないでください。Markdown が必要な場合は、YAML 検証後に「互換出力」「Markdown出力」「画像生成バッチ準備」として生成します。

YAML IR では、少なくとも次を分離して持つ。

- `meta`: ページ/コマ用途、読み順、比率
- `manga`: 画風、ページレイアウト、文字描画方針
- `scene`: 場所、時間、背景
- `character_ids`: 登場人物の `character_id`
- `panels[]`: コマごとの `summary` / `subjects` / `composition` / `text` / `prompt_tags` / `translation`（任意で `negative_tags` / `omit_negative_tags`。**コマ単位ネガ**の書き方は `manga_tag.md` の「コマ別ネガ」）
- `technical.negative_tags`: ページ共通のネガ断片（**コマ生成** `--source step1-panels` では、各コマの合成 `negative_prompt` に含める）

### `manga.genre_tags` / `manga.visual_tags`（Step1 の `tag` 行に直結する）

`tools/novel_prompt_ir_export_md.py` の `panel_tags()` は、互換 `manga/manga_XX.md` の **各コマ `### Step1` の `tag` 行**に、コマ用のスタイル断片のあと **`manga.genre_tags` と `manga.visual_tags` をそのまま連結**する。`tools/forge_novel_manga_batch.py`（YAML 入力）のタグ合成も同様にページの `manga` 節を読む。

- **原則（フルカラー運用）**: **`monochrome` と `screentone` を `genre_tags` および `visual_tags` に入れない。** 雛形 `tools/manga_prompt_ir/examples/manga_page.yaml` など**古い例**に従うと、白黒・トーン紙風のトークンが混ざり、**互換 Markdown の「カラー」表記や、カラー指向モデル（NovelAI 等）の意図と矛盾**しやすい。
- **例外**: 作品またはページを**意図的にモノクロ漫画・スクリーントーン仕上げ**にするときだけ、`monochrome` / `screentone` を置く。その場合は **`color_palette.mode`**（または `render_instruction` 等）と説明文をモノクロ前提で揃える。
- **カラーで画風を足すなら**（例）: `full_color`・`anime_coloring`・`cel_shading`・`clean_lineart` など、プロバイダと合わせた語を **`visual_tags`** や **`panels[].prompt_tags`** に載せる。

**`scene` の英語フィールド（タグ行・txt2img）**  
`location_en` は**必須（非空）**。`time_of_day` / `weather` / `background_notes` を書いたら、対応する `time_of_day_en` / `weather_en` / `background_notes_en` も**必須**（`tools/manga_prompt_ir/schemas/manga_page.py` の `Scene` で検証）。`tools/manga_prompt_ir/scene_prompt.py` は **`*_en` のみ**参照し、日本語の `location` 等にはフォールバックしません。欠けは LLM 側で英語行を補ってから保存する。

`Step1` / `Step2` は生成モード名として残します。YAML 直読では、`Step1` 相当は `panels[]` の詳細情報、`Step2` 相当は `manga.panel_layout` と各コマの要約・配置から組み立てます。正本 YAML に戻せるよう、コマ番号、人物、場所、行為、セリフ話者、効果音、段・大小・読み順を省略しない。

キャラクターの服装・状態差分は、`panels[].subjects[]` に `variant_id` / `prompt_variant_id` / `costume_variant` のいずれかで明示する。値は `tag/characters/<character_id>.yaml` の `prompt_variants[].variant_id` と一致させる。指定がある場合、画像生成バッチは基本衣装ではなく該当バリアントの `danbooru_tags` を優先して注入する。

### POV・部分アップと `subjects[]`（タグ注入の主役を誰に合わせるか）

`forge_novel_manga_batch.py` は `subjects[]` の `character_id` を手がかりに、各人物の `tag/characters/<id>.yaml` から固定特徴・バリアントを注入する（`character_snapshots` 優先の上で）。**同じコマ内でも「画の主役＝外見タグの基準にすべき人物」は、行為の主導者とは限らない。**

- **原則**: フレームで**面積・意味の中心になっている身体**の持ち主を、`subjects[]` の**先頭に近いほど主**として書く。複数人物がいるときは「誰の体型・肌・衣装タグが結果を決めるか」がその人物側になるように並べる。
- **一人称・POV**（`prompt_tags` に `pov`・`first_person_view`・`male perspective` 等がある、または本文上そういう視点）で**視界いっぱいに相手が映る**構図では、**視線の先にいる相手**を `subjects` の**第一**にし、その人物の `variant_id` で、画面に占める**腰・太もも・胸**などの状態を示す。視点側の人物は手・腕だけ・縁だけでもよいが、そのときは**別の `subjects` エントリ**として続け、`description` で「手のみ」「前景から伸びる腕のみ」と限定する。
- **よくある誤り**: 行為の主体だけを `character_id` にし、**画面上は相手の裸体・腰などが主**なのに視点人物だけを載せる——注入タグが視点人物側に寄り、**見えている身体とずれる**。その場合は**見えている側を主 subject** にする。
- **話者と画の主役**: モノローグの話者が視点人物でも、画が相手の部位中心なら **`text` は話者、`subjects` の先頭は相手**と分けて書くと混線しない。

### クローズアップ・接写と `prompt_tags`（見えている部分の特徴を書く）

全身が画面に入らないコマでは、**「どの人物か」だけを英語タグで粗く示すのではなく、フレームに入っている部位・肌・形状・状態**を `prompt_tags` に厚く載せる運用を推奨する。

- **`subjects[]`**: 引き続き**誰の身体か**（タグ注入の帰属）を示す。腰だけ・手元だけでも、`character_id` と `description` で「誰の・画面に映っている範囲はどこまでか」を明記する。
- **`prompt_tags`**: **画に実際に写っている見え方**を優先する。部位・画角・質感の例: `slim waist` `midriff` `thighs` `trembling hands` `extreme close-up` `face focus` `parted lips` `sweat` `flushed` など。**フレーム外の要素**（全身コーデ・画面に入っていない髪型の明示など）は無理に足さず、全身向けの人物ラベルだけで埋めない。キャラの固定特徴の注入は **`subjects` とキャラ YAML／スナップショット**が担うので、`prompt_tags` は**そのコマで絵を決める局所的な記述**に寄せる。
- **`summary` / `description`（日本語）**: 「誰の・どの部位が・どんな状態で」写っているかを部位レベルで書き、`prompt_tags` の英語と矛盾させない。

語彙の引き出しは `_how_to/manga_tag.md` の部位・体勢の例と併用する。

### 手元・手と手など「キャラID注入を載せない」コマ

**可能。** `forge_novel_manga_batch.py` のタグ組み立て（`yaml_panel_tags`）では、**`subjects[].character_id` が無い**とき **`tag/characters/<id>.yaml` 由来の固長タグ列は付かない**（`subject_snapshot` もヒットしない）。代わりに `subject_tag_line_token()` が **`tag_token` → `description_en` → `description`** の順で短いトークンを1つ足す（実装は `tools/manga_prompt_ir/scene_prompt.py`）。**手と手をつなぐ接写だけ**にしたいときは次のとおり。

- **`character_id` を付けない** `subjects` を、写る手の数だけ並べる（例: 2エントリ）。英語の見え方は **`tag_token`** または **`description_en`** にまとめる（例: `slender female hand`, `larger male hand`, `interlocked fingers`, `holding hands`）。日本語の `description` は編集用メモとして残してよい。
- **`prompt_tags`** に画角・肌の質感・握り方などを足す。**キャラYAMLが載らないぶん、肌の明暗・手の大きさ差などは英語で明示**する。
- **検証**: 既定の `type: human` のまま `character_id` 無しだと `novel_prompt_ir_validate.py` が「人物subjectに character_id がありません」と**警告**する。部位・手だけのブロックとして書くなら **`type` を `hands` / `detail` / `object` 等**（`human` `person` `character` 以外）にすると、当該警告を避けられる。
- **ページの `character_ids`**: そのページの別コマで同じ二人を `character_id` 付きで使っていれば宣言との整合は取れる。手だけのコマだけでは二人が未宣言に見える場合は**警告が出る**ので、`--strict-quality` 運用では当該ページの構成を確認する。
- **トレードオフ**: 注入を外すと**髪・目・肌の自動一貫性は効かない**。必要な差は `tag_token` / `prompt_tags` で足す。

例（概念スケッチ）:

```yaml
# subjects のみ抜粋。character_id なし。
- description: 左側から差し出される細い手（編集メモ）
  description_en: slender hand, fair skin, reaching from left
  type: hands
  pose_action: fingers loosely curled
- description: 右側から包み込む大きめの手（編集メモ）
  description_en: larger hand, interlocked fingers, holding hands
  type: hands
  pose_action: gentle grip
```

品質の見方は `.rulesync/skills/manga-tag-quality-gate`（誰が写っているか・セリフ帰属）。POV では「視線の先の人物が `subjects` とタグで説明されているか」を確認する。

ページYAMLを単体で読める原盤にするため、`character_snapshots` にそのページで使う登場人物の外見・衣装・バリアントタグを埋め込む。作成・更新は次で行う。

```bash
python tools/novel_prompt_ir_embed_snapshots.py novels/<作品>
```

生成バッチは `character_snapshots` があればこれを最優先し、無い場合だけ `tag/characters/*.yaml` を参照する。

### バリアントとタグ注入の優先（曖昧にしないための正本）

**小説→ページYAML起こしの手順の説明は本ファイル（`manga.md`）を正とする。** 次の表は、**実装** `tools/forge_novel_manga_batch.py`（`subject_snapshot` / `selected_subject_variant_id` / `character_ir_tags`）と揃えたものである。`manga_tag.md` は**シーン用の英語タグ例・語彙**の参照であり、ここに無い「variant の機械的な優先」は定義しない。

| 優先度 | 何が起きるか |
|--------|----------------|
| 1. `character_snapshots` | ページにスナップショットがあり、`subjects` の variant に対応するエントリがあれば **その `fixed_tags` + `variant_tags` を最優先**（コマに寄らずページ単位の埋め込み） |
| 2. キャラ YAML の `prompt_variants` | スナップショットが無い／当たらないとき、各 `subjects[]` について次の**3キーは先に書かれた方が採用**（実装と同一）: **`prompt_variant_id` → `costume_variant` → `variant_id`**。値は `tag/characters/<id>.yaml` の `prompt_variants[].variant_id` と**文字列一致**で探す。 |
| 3. ベース衣装・固定特徴 | variant が空、または ID が YAML に存在しないとき **`costume.outfit_tags` / `manga_rules.consistency_tags` 等**へフォールバック（**意図と違う絵になりうる**）。`novel_prompt_ir_validate.py` が警告しうる。 |

- **検証の正本**: `python tools/novel_prompt_ir_validate.py`（本番前は `--strict-quality` 推奨）。スキーマ違反は exit 1、品質は警告（`--strict-quality` で失敗扱い）。
- **英語タグの引き出し**（行動 等）: `_how_to/manga_tag.md` を参照。合格条件の定義ではない。

### variant はコマ単位ではなくタイムラインで決める

小説本文からページYAMLへ落とすとき、`variant_id`（および `prompt_variant_id` / `costume_variant`）は **その場その場のコマだけを見て付け替えない**。まず `_novel_text` の **時系列と場の連続性** を踏まえ、**どの区間で衣装・身体的状態が同じか／どの節目で変わるか** を決める。

- **連続した同一場面**（同じ時間帯・同じ空間で、着替えやフェーズ移行がまだ起きていない）では、登場キャラの variant は **原則として一定**とする。コマが進んで調整するのはポーズ・アングル・接写・セリフなど **コマ固有の記述**であり、**variant をコマごとに気まぐれに変えない**（連続コマで、理由なく服装や肌の見え方だけが切り替わるのを防ぐ）。
- variant を変えてよいのは、**本文上はっきり境目があるとき**に限る（移動、時間経過、着脱・治療段階の推移など）。迷ったら「直前のページ／コマと **まだ同じ状況か**」を問い、同じなら **同じ variant を維持**する。
- **ページをまたいでも**、ひと続きの場面なら variant は **引き継ぐ**。場当たり的な付け替えは、絵の一貫性だけでなく、後からの **validate や `character_snapshots`** とも齟齬を生みやすい。

## ページ YAML の型・Step1 互換の元データ（ドキュメントへ移設）

**Monogatari Coach（`_how_to`）では参照されない**、ページ IR の形と旧フォーマット差分・最小 YAML 例は、操作マニュアル **[`docs/image-generation/manga-prompt-ir.md` の「ページ YAML の最小構造と Step1 互換出力の元」](../docs/image-generation/manga-prompt-ir.md#yaml-minimal-step1)** に置いてあります（互換 `manga_XX.md` の Step1 は、この YAML をエクスポートした結果です）。

---

## ツール・タグ出力ドキュメントへのリンク

- **検証・バッチ・ネガ合成・novelai-pipe-tags**: [docs/image-generation/manga-prompt-ir.md](../docs/image-generation/manga-prompt-ir.md)
- **互換 Step1/Step2 の全文テンプレ・実例・レイアウト・運用メモ**: [docs/image-generation/manga-tag-generation.md](../docs/image-generation/manga-tag-generation.md)

ネガの語彙・運用例は引き続き manga_tag.md の「コマ別ネガ」を参照してください。
