# 漫画タグ生成（互換 Markdown・Step1 / Step2）

**読者**: Manga Tag Mode で **LLM や人間が参照する**、互換 `manga_XX.md` の書式・長い作業指示・出力例・レイアウト指針です。互換 Markdown は、YAML IR からエクスポートする**人間向けの可読副本**として、手作業・推敲・既存バッチ連携に引き続き使います。

**正本の編集**: 運用上は **`novels/<作品>/manga/pages/*.yaml`**。本文書は「Markdown に出力されるときの形」と「タグ作業の叱り方」の参照です。**ツール・コマンド・検証**は [manga-prompt-ir.md](manga-prompt-ir.md) を参照してください。

**英語タグの語彙**: [`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md)（ユーザーが `_how_to/manga_tag.md` をカスタムしている場合はそちら優先）。

**Step2 の言い換え表・編集前チェック**（創作技法の正本）: [`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)。本書の Step2 節はテンプレ・仕様**補助**に留め、表の重複は置かない。

---

## 互換出力: step1

以下は `manga/manga_XX.md` へ出力する互換 Markdown の形式です。新規の漫画タグ作成では、先に `manga/pages/manga_XX_pYY.yaml` を作成・検証してからこの形へエクスポートしてください。

stable diffusion,novelaiで漫画1ページを描画してもらうような、タグを作成してください、カラーのページにしたいです。
nanobanana, GptImage1のようなツールでもそのまま使えることを考えています。
タグ生成の際には manga_tag.md（英語タグの語彙例）と、[ページ YAML の型・Step1 互換の元データ](manga-prompt-ir.md#yaml-minimal-step1)（[manga-prompt-ir.md](manga-prompt-ir.md)）も確認し参考にしてください
タグを付けるとき、誰が、どのような体勢で、誰に、背景はこう、のようなことを各コマで明確にしてください。
メッセージは日本語で応対してください
あと、内容については、3-7コマで、済むような形で。使った場所を教えてください
英語のタグに日本語の翻訳を後に追加してください。喋るコマの場合は吹き出しだけ日本語を入れるようにしてください。
各コマのタグを個別に出すようにして､最後にそれを束ねて全ページを一気に出す形にしてください。
1コマコマごとに場所 (Location),人の状態 (Characters' States),行っているアクション (Actions)などを明確にしてください。
誰の何にどうしたといったことは、文章で表記してください。
**step1 は「各コマを個別画像として確実に生成できる」ことを最優先**にしてください。**1つのコマにつき1つの tag を必ず対応**させ、**複数コマを1つの tag にまとめない**でください。
各コマには、**そのコマだけを見ても意味が通る最低情報**として、できるだけ次を入れてください。

- 誰が写っているか
- 誰に向けた行為か
- どこで起きているか
- 何をしている瞬間か
- どのセリフが誰のものか
- そのコマで見せたい情報や感情
- どの向きからのアングルか
- 直接的描写
- 人物の服装
- 必要な小道具や画面内情報（スマホ、剣、扉、アプリ画面、魔法陣など）

手元、足元、口元、目元、スマホ画面などの**部分アップ**は、**誰の部位か**、**何を伝えるためのコマか**まで文章で補ってください。
会話のあるコマでは、**話者**と、必要なら**聞き手**も分かるようにしてください。モノローグか発話かも曖昧にしないでください。
登場人物がいる場合は、**character.md と tag/<romaji>.md の固定特徴に矛盾しないこと**を前提にしてください。髪色・目・服装・体格・固定小物は勝手に変えないでください。
前後のコマとのつながりが重要な場合は、視線方向、立ち位置、持ち物の左右、負傷箇所などの**連続性**が崩れないようにしてください。
`誰か`, `人物`, `何かを見る`, `意味深な表情` のような曖昧語だけで止めないでください。

構図の工夫、アオリとフカン、アップとヒキなども適切にコマのメリハリを付けるのに入れてください。どの向きからの構図かについてもメリハリをつけてください。
ここではimagineで決して画像を生成しないでください。
日本の漫画のコマ割りについては必ず指定してください
縦長・横長・右中・左上のような**コマの向きや配置の固定指定は、必要な場合だけ入れてください**。不要なら入れないでください。
特に画像生成用の英語タグでは、**コマの向き（vertical, horizontal, landscape など）を機械的に毎回入れない**でください。

### コマのページ内位置（レイアウト）を明記する

**目的**: 「どのコマがページのどこに載るか」が無いと、ページ丸ごと生成や step2 を入力したときに**ただのカット列**になりやすい。スキル **`manga-tag-quality-gate`**（「8. レイアウト・読み順（Step1 / Step2 横断の確認）」）とも整合させる。

**step1 での書き方（どちらか必ず）**

1. **ページ配置の1行サマリ**を `### Step1` 直後（コマ列の前）に書く。均等な縦並びだけでもよい。  
   - 例: `ページレイアウト（読み順・上→下）: コマ①〜④を縦に四分割、横幅ほぼ均等。`  
   - 例: `ページレイアウト: 上段=コマ1（やや大）｜中段=コマ2・コマ3の横並び｜下段=コマ4（大ゴマ）。`
2. または、**各 `コマN:` の説明文の先頭**に、段・大致を短く付ける。  
   - 例: `コマ2: 【中段・左】 medium shot。〜`  
   - 例: `コマ4: 【最下段・横幅いっぱい】 感情のクライマックス。〜`

コマ単体画像だけを出す予定でも、**1 または 2 を入れておく**と、あとから精密ページ生成やページ化したときにブレにくい。

**step2 での書き方**

- **ページ生成（1ページ1枚）を使う場合は、各コマに「段・左右・大小」が読めるようにする**（事実上必須）。均等な縦Nコマだけなら、`均等Nコマ・上から①→②→…と読む` の**一行**でよい。
- 下記「step2 での出力例」のように、**上段／中段／下段**・**最下段・大コマ**などを**コマ番号ごと**に必ず紐づける。

**英語の `tag:` 行**: コマ位置は**日本語のコマ説明**で担う。タグに `vertical panel` 等を毎コマ足す必要はない（上記「機械的に毎回入れない」に同じ）。

「自然言語で状況説明＋箇条書きでコマを並べる」スタイル

## 互換出力: step1 での出力例

```
## step1
カラー漫画、1ページ6〜8コマ、少年ジャンプ風の迫力あるバトルシーン、日本の漫画のコマ割り
登場人物：黒髪の剣士「零」（傷だらけ、目が鋭い）、金髪の魔法使い少女「ルナ」
ページレイアウト（目安）: 上段=コマ1（ワイド）｜中段=コマ2・3の横並び｜下段=コマ4・5・6を横三連（コマ6をやや大きめ）

コマ1: 【上段・横幅広め】見開き大ゴマ気味、零が剣を構えて敵の群れを睨む、背景に炎、迫力重視
セリフ：「来い…全部まとめて斬ってやる」
tag:  
dynamic wide angle manga panel, shonen jump style, dramatic low angle shot, black-haired scarred swordsman Rei gripping sword tightly, sharp intense eyes glaring forward, surrounded by shadowy enemy horde, blazing fire background, intense atmosphere, action manga, detailed lineart, speed lines, high contrast, epic battle opening scene

コマ2: 【中段・左】 ルナが後ろで魔法陣を展開、青い光エフェクト
セリフ：「零！援護するよ！」
tag:  
shonen manga style, beautiful blonde magical girl Luna standing behind, casting large glowing blue magic circle, intricate rune patterns, cyan light particles and sparkles, determined expression, wind blowing hair, support magic scene, dramatic backlighting, detailed magical effects, anime screentone

コマ3: 【中段・右】 零が敵の先頭へ踏み込み、斜めに斬りかかる瞬間
セリフ：なし
tag:  
fast-paced action manga panel, Rei performing powerful diagonal sword slash, forward stepping motion, impact frame, dynamic speed lines, black hair flowing, enemies directly ahead, dramatic shading, kinetic energy, battle tension

コマ4: 【下段・左】 斬撃の着弾で爆炎と瓦礫が広がる
セリフ：なし
tag:
explosive impact manga panel, violent burst of fire and smoke, debris flying outward, aftermath of sword slash, bright orange flames, shockwave emphasis, dynamic composition, dramatic destruction, intense battle atmosphere

コマ5: 【下段・中央】 爆発に巻き込まれた敵たちが悲鳴を上げて吹き飛ぶ
セリフ：「うわああっ」
tag:
enemy horde blown away manga panel, enemies screaming in pain, distorted faces, bodies thrown backward by explosion, smoke and sparks, dramatic high contrast shading, chaotic battle aftermath, action manga intensity

コマ6: 【下段・やや大ゴマ】 零が血まみれで立っている、ルナが駆け寄る、決めポーズ
tag:  
final victory pose manga panel, shonen jump climax scene, bloodied black-haired swordsman Rei standing tall breathing heavily, sword planted in ground, sharp eyes looking forward, wounds and torn clothes, blonde magical girl Luna running towards him worriedly, reaching out, dramatic back view of enemies defeated in background, dust and smoke, powerful atmosphere, detailed shading, heroic moment, intense emotion

```

## 互換出力: step2

**必ず併読（創作技法）**: Step2 用の短いチェックリスト・Step1 との違いは、**[`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)**（運用コピーは通常 `_how_to/manga_tag_step2.md`）。本節は長文テンプレとエクスポート仕様**中心**。

以下は `manga/manga_XX.md` へ出力する互換 Markdown の形式です。ページ生成向けの抽象レイアウトも、正本は YAML IR の `manga.panel_layout` / `panels[].composition` に保持します。

nanobanana, GptImage1のようなツールで、コマ割りと抽象度をのみ出す形
抽象度を上げる、「何をしている」という具体的な行動や接触描写を排除し、純粋に構図・位置関係・アングル・表情の配置だけに絞る
日本の漫画のコマ割りについては必ず指定してください

**各コマのページ内位置**（上段／中段／下段、左・右、大ゴマ／小コマ、横並びで何コマ分か）は、**ページ生成やレイアウト再現に使うため**に書く。均等な縦並びだけなら `均等Nコマ・上から読む` の一行でよい。step1 の「コマのページ内位置」節と同じ基準でよい。

コマの向きや画角ラベル（vertical 等）の固定は、**そのページで本当に必要な場合だけ**英語タグ側に足す。テンプレートとして毎回は入れない。ただし**段・左右・大小**の日本語による位置指定は、ページ生成では省略しにくい。

**Step2 の文章作法**（チェックリスト・言い換え表・抽象語の補足例・悪い例／良い例・モデレーション配慮）は **[`_how_to.example/manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)**（運用は `_how_to/manga_tag_step2.md`）に**正本として集約**した。本書の長文テンプレで LLM に渡すときも、同ファイルをコンテキストに含めるとよい。

**（機械との関係）** **IR の `step2_summary` / `summary` や互換 Markdown** は、上記 **`manga_tag_step2.md`** の作法に従って書く。`novel_prompt_ir_validate.py` は **言い換え内容を自動では検証・適用しない**（[`_how_to.example/manga_tag.md`](../../_how_to.example/manga_tag.md) の置き換え表と同様、**手で IR に反映するまで完了とみなさない**）。

**（表の機械置換）** [`manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md) の「言い換えの目安」表と同内容の置換は、ルール YAML を **`forge_novel_manga_batch.py`**（`--source step2-pages`）または **`novel_prompt_ir_export_md.py`** 実行時に、環境変数 **`MONOCRI_STEP2_PARAPHRASE=1`** または **`--step2-paraphrase`** で**生成直前の Step2 本文**へ適用できる（**`--no-step2-paraphrase`** でオフ。IR ファイルは変わらない）。**既定は `apply_mode: whole_text`**（`avoid` に部分一致したら**そのコマの Step2 本文全体**を `use` に差し替え）。従来の文中だけの部分置換はルール YAML に **`apply_mode: substring`**。探索順は **`MONOCRI_STEP2_PARAPHRASE_RULES`** → **`_how_to/step2_paraphrase_rules.yaml`** → **`tools/manga_prompt_ir/data/step2_paraphrase_rules.yaml`**。

**互換 Markdown の Step2（自動エクスポート）** は `tools/novel_prompt_ir_export_md.py` が、各ページ YAML の `manga.panel_layout`・`meta.reading_order`・各 `panels[].composition.layout`・**コマ要約**から機械的に組み立てます（ページ生成バッチの `yaml_page_step2_text` も同じ情報源です）。**コマ要約は `panels[].step2_summary` が非空ならそちらを優先**し、無い場合のみ `panels[].summary` を使います（Step1 は引き続き `summary` が見出し本文）。見出しは各 `## Page N` の直下に付く `### Step2` です。

加えて、**登場人物の固定見た目**は次の**複合**で付与されます（`tools/forge_novel_manga_batch.build_step2_panel_line`）。手で `summary` に髪色を毎回書かなくても、正本の YAML に沿って追従します。

1. **ページの `character_snapshots[]`** に `appearance_summary` がある場合 → その **自然文**を最優先（`名前: appearance_summary`）。**`costume_summary` は Step2 の【固定見た目】には含めない**（衣装・状況の長文が付きやすいため。IR 正本としては引き続き保持してよい）。
2. 上記がなく **`fixed_tags` / `variant_tags` がある場合** → 英語タグ列を短く連結（長い場合は先頭16個まで）。
3. いずれも弱い、または補完として **`tag/characters/<id>.yaml`** の `appearance`（髪色・髪型・目色・肌・`species_features`）と `costume.accessories`（固定小物）、`distinctive_features`（先頭3件）を **日本語ラベル付き**で連結。それでも空に近い場合は **`character_tags` の先頭数件**にフォールバック。

同一コマに同じ `character_id` が複数あっても **1回だけ**出ます。`character_id` のない subject（小物だけのコマ等）は **固定見た目節を出しません**。

Step2 だけ描写を弱めたいときは **同じコマに `step2_summary` を追加**し、コマ生成向けの `summary` は具体的なまま残せます。手書きで直す場合も、**IR の `step2_summary` / `summary` と `composition.layout`** を正本にし、再エクスポートすると `manga/manga_XX.md` の Step2 が追従します。

## 互換出力: step2 での出力例（エクスポータ実物に近い形）

```
### Step2
1ページ5コマ。上段=コマ1（大）｜中段=コマ2・3｜下段=コマ4・5。読み順は right_to_left。
- コマ1: 上段・大コマ。路地の奥に敵の列が見える wide shot。状況の導入。【固定見た目】零・黒髪ショート、目は鋭い灰青、肌健康的、種族特徴 human｜ルナ・金髪ロング、青い瞳、肌淡く透明感…（以下略）
- コマ2: 中段・右。零が剣を構え前傾で敵列を睨む medium shot。【固定見た目】零・（同上の省略または IR から再掲）
```

1行目は常に `1ページ{N}コマ。{panel_layout}。読み順は {reading_order}。`、続く各行は **`- コマ{panel_id}: {layout}。{step2_summary または summary}`** に、登場キャラがいれば **` 【固定見た目】`** と続きます（複数キャラは **` ｜ `** で連結）。`layout` が空なら `コマN: 。{…}` のように見えることがあります。本文の抽象度・安全な言い換えは、**[`manga_tag_step2.md`](../../_how_to.example/manga_tag_step2.md)** のチェックリストと言い換え表に従って **`step2_summary`（無ければ `summary`）** に込めてください。**髪・目・肌・種族・小物の細目は IR の character／snapshot に寄せる**と、step2 本文が安定します。

---

## プロっぽく見せるための調整ポイントの例

### ① コマサイズの強弱

* コマ1：やや大
* コマ2：小
* コマ3：小
* コマ4：中
* コマ5：最大

👉 「情報 → 接近 → 包囲 → 感情爆発」の流れ

### ② 視線誘導

* 1 → 2 → 3 → 4 → 5 のZ型
* キャラの視線・動きも同じ方向にする
  👉 読みやすさが段違いに上がる

### ③ 演出のコツ

* コマ2〜4は“間を詰める”（コマ間狭める）
* コマ5前だけ余白を広く
👉 クライマックスが映える

---

## 運用メモ（生成先の切り分け）

- **step1 は「コマ生成」用**です。各コマを個別画像として出す前提で、**Forge / NovelAI / Grok** の入力元に使います。
- **step1 は「精密ページ生成」用**にも使えます。各コマの詳細指示を保ったまま **1ページ全体を1枚にまとめたい場合**は、**Grok** の入力元として使います。
- **step2 は「ページ生成」用**です。1ページ全体を1枚の漫画画像として出す前提で、**Grok** の入力元に使います。
- **step1 / step2 は生成入力用の互換出力**です。Manga Tag Mode では、まず YAML IR を作り、検証後に必要な形式へ出力します。
- **step1 / step2 からページ生成するとき**は、作品の **`tag/*.md`** にある通常時 Danbooru Tags を固定特徴アンカーとして参照できるよう、**本文中にキャラ名を明記**してください。
- **Nanobanana は導入予定のページ生成系**として想定します。導入後は step2 の入力先に加えます。
- **Nanobanana 導入後は step1 / step2 のページ生成系入力先に加える想定**です。
- **Forge / NovelAI は既定運用ではページ生成の正式対応先に含めません**。これらは step1 のコマ生成向けとして扱います。
- 会話で指定するときは、**「コマ生成」「各コマを出力」「step1から生成」**、**「精密ページ生成」「step1をそのままページ化」**、**「ページ生成」「1ページ丸ごと」「step2から生成」** のように明示してください。
