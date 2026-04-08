## step1 
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

構図の工夫、アオリとフカン、アップとヒキなども適切にコマのメリハリを付けるのに入れてください。
ここではimagineで決して画像を生成しないでください。
日本の漫画のコマ割りについては必ず指定してください

「自然言語で状況説明＋箇条書きでコマを並べる」スタイル
## step1 での出力例
```
## step1
縦長マンガ、1ページ6〜8コマ、少年ジャンプ風の迫力あるバトルシーン、日本の漫画のコマ割り
登場人物：黒髪の剣士「零」（傷だらけ、目が鋭い）、金髪の魔法使い少女「ルナ」

コマ1: 見開き大ゴマ気味、零が剣を構えて敵の群れを睨む、背景に炎、迫力重視
セリフ：「来い…全部まとめて斬ってやる」
tag:  
dynamic wide angle manga panel, shonen jump style, dramatic low angle shot, black-haired scarred swordsman Rei gripping sword tightly, sharp intense eyes glaring forward, surrounded by shadowy enemy horde, blazing fire background, intense atmosphere, action manga, detailed lineart, speed lines, high contrast, epic battle opening scene

コマ2: ルナが後ろで魔法陣を展開、青い光エフェクト
セリフ：「零！援護するよ！」
tag:  
shonen manga style, beautiful blonde magical girl Luna standing behind, casting large glowing blue magic circle, intricate rune patterns, cyan light particles and sparkles, determined expression, wind blowing hair, support magic scene, dramatic backlighting, detailed magical effects, anime screentone

コマ3〜5: 連続アクション（斬撃→爆発→敵の悲鳴）
tag:  
fast-paced action sequence, 3 consecutive manga panels in one image, dynamic speed lines,  
panel1: Rei performing powerful diagonal sword slash, motion blur, impact frame, black hair flowing,  
panel2: massive explosion of fire and smoke after slash connects, debris flying,  
panel3: enemies screaming in pain, distorted faces, being blown away, dramatic shading, shonen jump battle intensity, monochrome + selective color, kinetic energy

コマ6: 零が血まみれで立っている、ルナが駆け寄る、決めポーズ
tag:  
final victory pose manga panel, shonen jump climax scene, bloodied black-haired swordsman Rei standing tall breathing heavily, sword planted in ground, sharp eyes looking forward, wounds and torn clothes, blonde magical girl Luna running towards him worriedly, reaching out, dramatic back view of enemies defeated in background, dust and smoke, powerful atmosphere, detailed shading, heroic moment, intense emotion

```

## step2 
nanobanana, GptImage1のようなツールで、コマ割りと抽象度をのみ出す形
抽象度を上げる、「何をしている」という具体的な行動や接触描写を排除し、純粋に構図・位置関係・アングル・表情の配置だけに絞る
日本の漫画のコマ割りについては必ず指定してください

以下のような出力でお願いします

## step2 での出力例
```
## step2
縦長カラーマンガ、1ページ5コマ、日本の漫画のコマ割り
各コマの左上または中央に太字の白抜き数字（1, 2, 3, 4）を明確に描き込んでください。漫画ページ全体のレイアウトとして。

---
### ■ 各コマの役割＋配置意図

#### ■コマ1（左上）

* フカン long shot
* 「状況説明（誰がどこにいるか）」
* 視線のスタート地点
  上段で最も“情報量が多い導入”

---

#### ■コマ2（右上）

* アオリ close up（A）
* 最初の動き（距離を詰める）
* 読者の視線を「人物中心」に寄せる

 右上は“初動のアクション”に最適

---

#### ■コマ3（左中）

* 横アングル medium（B）
* 背後から接近＝「包囲の始まり」
* コマ2からの流れを受けて左へ戻す

 視線を折り返すポイント

---

#### ■コマ4（右中・横長推奨）

* eye level dynamic（C）
* 右からの侵入＝囲み完成へ
* 少し横長にすると「動き」が出る

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
* コマ4：中（横長）
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

