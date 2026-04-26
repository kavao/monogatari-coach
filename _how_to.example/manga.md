## 構造化IR優先（manga-prompt-ir）

新規の漫画ページ・漫画コマは、まず **`manga-prompt-ir`** の `MangaPagePrompt` 構造へ落とす。

- 人間編集用の正本: `novels/<作品>/manga/pages/manga_XX_pYY.yaml`
- 既存バッチ互換: `novels/<作品>/manga/manga_XX.md`
- `manga_XX.md` は `tools/forge_novel_manga_batch.py` のための互換出力層として扱う
- 中間データは作り直し可能だが、**誰が・どこで・何をし・誰に話し・どのコマがどんな役割か**は失わない

**Manga Tag Mode の初手は YAML IR 作成です。**
`manga/manga_XX.md` を直接新規作成して正本にしないでください。Markdown が必要な場合は、YAML 検証後に「互換出力」「Markdown出力」「画像生成バッチ準備」として生成します。

YAML IR では、少なくとも次を分離して持つ。

- `meta`: ページ/コマ用途、読み順、比率
- `manga`: 画風、ページレイアウト、文字描画方針
- `scene`: 場所、時間、背景
- `character_ids`: 登場人物の `character_id`
- `panels[]`: コマごとの `summary` / `subjects` / `composition` / `text` / `prompt_tags` / `translation`
- `technical.negative_tags`: ページ側の negative tags

`Step1` / `Step2` は `manga/manga_XX.md` 互換出力の形式名です。正本 YAML に戻せるよう、コマ番号、人物、場所、行為、セリフ話者、効果音、段・大小・読み順を省略しない。

## YAML IR の最小構造例

以下は `manga/pages/manga_01_p01.yaml` の最小構造例です。詳細な定義は `manga-prompt-ir` スキルの `schemas/manga_page.py` と `examples/manga_page.yaml` を参照してください。

```yaml
manga_id: "manga_01"
page_number: 1
meta:
  purpose: "コマ生成（step1-panels）"
  read_order: "右から左"
manga:
  style: "カラー漫画、少年ジャンプ風"
  panel_layout: "上段=コマ1（ワイド）｜中段=コマ2・3横並び｜下段=コマ4（大ゴマ）"
scene:
  location: "廃工場の内部"
  time: "夜、非常灯のみ"
  background_tags: "abandoned factory interior, emergency lighting, dark atmosphere"
character_ids:
  - "rei"
  - "luna"
panels:
  - panel_number: 1
    summary: "零が敵の群れを睨む。上段・横幅ほぼ全体の大ゴマ"
    subjects:
      - character_id: "rei"
        action: "剣を構えて敵の群れを正面から睨む"
        expression: "鋭い目つき、傷だらけ"
    composition:
      layout: "上段・横幅全体"
      camera: "ローアングル"
      shot_type: "wide"
    text:
      dialogue:
        - speaker: "rei"
          line: "来い……全部まとめて斬ってやる"
    prompt_tags: "dynamic wide angle manga panel, shonen jump style, dramatic low angle shot, black-haired scarred swordsman Rei gripping sword tightly, sharp intense eyes glaring forward, blazing fire background"
technical:
  negative_tags: "low quality, blurry, deformed"
```

## YAML → Step1 / Step2 のフロー

```
[本文 _novel_text/novel_textXX.md]
  ↓ 読み込み・コマ化
[manga/pages/manga_XX_pYY.yaml]  ← 正本（ここを編集する）
  ↓ tools/novel_prompt_ir_validate.py（型・参照検証）
  ↓ tools/novel_prompt_ir_export_md.py（互換出力）
[manga/manga_XX.md]  ← 互換出力（バッチ生成向け・直接編集しない）
  ├─ Step1  → tools/forge_novel_manga_batch.py --source step1-panels（コマ生成）
  ├─ Step1  → --source step1-pages（精密ページ生成）
  └─ Step2  → --source step2-pages（ページ生成）
```

**修正は必ず YAML IR 側へ入れ、再エクスポートして `manga_XX.md` を更新する。`manga_XX.md` を直接書き換えて正本扱いにしない。**

## 互換出力: step1
以下は `manga/manga_XX.md` へ出力する互換 Markdown の形式です。新規の漫画タグ作成では、先に `manga/pages/manga_XX_pYY.yaml` を作成・検証してからこの形へエクスポートしてください。

stable diffusion,novelaiで漫画1ページを描画してもらうような、タグを作成してください、カラーのページにしたいです。
nanobanana, GptImage1のようなツールでもそのまま使えることを考えています。
タグ生成の際にはmanga_tag.mdも確認し参考にしてください
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
- 直接的描写
- 人物の服装
- 必要な小道具や画面内情報（スマホ、剣、扉、アプリ画面、魔法陣など）
手元、足元、口元、目元、スマホ画面などの**部分アップ**は、**誰の部位か**、**何を伝えるためのコマか**まで文章で補ってください。
会話のあるコマでは、**話者**と、必要なら**聞き手**も分かるようにしてください。モノローグか発話かも曖昧にしないでください。
登場人物がいる場合は、**character.md と tag/<romaji>.md の固定特徴に矛盾しないこと**を前提にしてください。髪色・目・服装・体格・固定小物は勝手に変えないでください。
前後のコマとのつながりが重要な場合は、視線方向、立ち位置、持ち物の左右、負傷箇所などの**連続性**が崩れないようにしてください。
`誰か`, `人物`, `何かを見る`, `意味深な表情` のような曖昧語だけで止めないでください。

構図の工夫、アオリとフカン、アップとヒキなども適切にコマのメリハリを付けるのに入れてください。
ここではimagineで決して画像を生成しないでください。
日本の漫画のコマ割りについては必ず指定してください
縦長・横長・右中・左上のような**コマの向きや配置の固定指定は、必要な場合だけ入れてください**。不要なら入れないでください。
特に画像生成用の英語タグでは、**コマの向き（vertical, horizontal, landscape など）を機械的に毎回入れない**でください。

### コマのページ内位置（レイアウト）を明記する

**目的**: 「どのコマがページのどこに載るか」が無いと、ページ丸ごと生成や step2 を入力したときに**ただのカット列**になりやすい。スキル **`manga-tag-quality-gate`**（§10 コマ割り・ページレイアウト）とも整合させる。

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
以下は `manga/manga_XX.md` へ出力する互換 Markdown の形式です。ページ生成向けの抽象レイアウトも、正本は YAML IR の `manga.panel_layout` / `panels[].composition` に保持します。

nanobanana, GptImage1のようなツールで、コマ割りと抽象度をのみ出す形
抽象度を上げる、「何をしている」という具体的な行動や接触描写を排除し、純粋に構図・位置関係・アングル・表情の配置だけに絞る
日本の漫画のコマ割りについては必ず指定してください

**各コマのページ内位置**（上段／中段／下段、左・右、大ゴマ／小コマ、横並びで何コマ分か）は、**ページ生成やレイアウト再現に使うため**に書く。均等な縦並びだけなら `均等Nコマ・上から読む` の一行でよい。step1 の「コマのページ内位置」節と同じ基準でよい。

コマの向きや画角ラベル（vertical 等）の固定は、**そのページで本当に必要な場合だけ**英語タグ側に足す。テンプレートとして毎回は入れない。ただし**段・左右・大小**の日本語による位置指定は、ページ生成では省略しにくい。
ただし、**抽象度を上げても意味は落とさない**でください。`step2` でも最低限、**誰が主役のコマか**、**誰と誰の関係を見るコマか**、**何を伝える役割のコマか**、**セリフがあるなら誰の発話か**は読めるようにしてください。
`step2` はレイアウト用ですが、人物の帰属が消えるほど抽象化しないでください。部分アップのコマでは、何の部位を、何の意味で置くのかを短く添えてください。
**`接触` `忍耐` `対峙` `緊張` のような抽象名詞だけでコマ説明を終えない**でください。**外から見て分かる構図情報**として、誰がどこにいて、どちらを向き、どの距離感で、どの表情で配置されるかに言い換えてください。
`step2` は**行為を消す**のではなく、**行為を構図に言い換える**イメージです。たとえば `接触` ではなく `右手を差し出す人物と、それを正面から見る相手の bust shot`、`忍耐` ではなく `うつむき気味で口を結び、肩に力が入った人物の close up` のように書いてください。
**悪い例**: `接触`, `忍耐`, `信頼の揺らぎ`, `不穏`
**良い例**: `机越しに向かい合う二人。左の人物が身を乗り出し、右の人物は椅子に浅く座って視線を受け止める`, `俯いた人物の目元と強く結ばれた口元の close up。背景を抜いて感情の硬さを見せる`
**step2 の目的のひとつは、生成AI側のモデレーションに触れやすい強い接触・暴力・生々しい身体描写を直接書かずに、人物の構図とページ設計を安全に伝えること**です。そのため、刺激の強い行為名を前面に出すのではなく、**人物の配置、視線、距離感、画面内の主従、表情、手元や立ち位置**として言い換えてください。
ただし、安全寄りにぼかすことと、何が見えるかを曖昧にすることは別です。**「誰がどこに立ち、誰を見ているか」まで見える説明**は残してください。
言い換えの目安:
- `抱きつく` → `距離が近い二人。片方が相手の胸元へ寄り、もう片方がそれを見下ろす構図`
- `殴りかかる` → `大きく振りかぶった腕と、それを正面から受ける相手の緊張した構図`
- `押し倒す` → `上下の位置差が強い二人の配置。上側の人物が画面手前を占め、下側の人物が見上げる`
- `流血した負傷` → `乱れた衣服、苦痛の表情、体勢の崩れでダメージを示す`

以下のような出力でお願いします

## 互換出力: step2 での出力例
```
## step2
カラーマンガ、1ページ5コマ、日本の漫画のコマ割り
各コマに識別しやすい番号を振ってください。**各コマについて、ページ内の段（上／中／下）と大小・役割**を本文に含めてください（均等縦並びならその旨を一行で）。

---
### ■ 各コマの役割＋配置意図

#### ■コマ1

* フカン long shot
* 「状況説明（誰がどこにいるか）」
* 視線のスタート地点
  上段で最も“情報量が多い導入”

---

#### ■コマ2

* アオリ close up（A）
* 主役が相手へ身を乗り出し、距離が縮まったことが見て取れる構図
* 読者の視線を「人物中心」に寄せる

 初動の圧力を見せる役割

---

#### ■コマ3

* medium shot（B）
* 中心人物の背後に別人物が入り、包囲が始まったと読める配置
* コマ2からの流れを受けて視線を折り返す

 視線を折り返すポイント

---

#### ■コマ4

* eye level dynamic（C）
* 右側からさらに別人物が画面へ入り、囲まれた状態が完成する見え方
* 必要なら横方向の広がりを使って「動き」を出す

 中段で最も“動き”を強調

---

#### ■コマ5（最下段・大コマ）

* Dutch angle bust up
* ABCに囲まれる＋中心人物の笑顔
* クライマックス

 ページの“重心”
 読後の印象を決定づける
```

---

### ■プロっぽく見せるための調整ポイントの例

#### ① コマサイズの強弱

* コマ1：やや大
* コマ2：小
* コマ3：小
* コマ4：中
* コマ5：最大

👉 「情報 → 接近 → 包囲 → 感情爆発」の流れ

---

#### ② 視線誘導

* 1 → 2 → 3 → 4 → 5 のZ型
* キャラの視線・動きも同じ方向にする
  👉 読みやすさが段違いに上がる

---

#### ③ 演出のコツ

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

