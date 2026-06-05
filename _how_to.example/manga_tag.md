# 取り扱い方（シーン用タグの語彙・例）

**役割分担**: **本文からページYAMLを起こす手順・IR構造・バリアントとタグ注入の優先・検証**は **`manga.md`** を正とする。本ファイルは **コマ・シーンに寄せた英語タグのリストアップ**（sfw/nsfw・体位・前戯など）と、タグを書くときの最低限の意味チェックに使う。**Step1（コマ生成・`prompt_tags`）向けの語彙正本**として使う。

- **Step2（ページ生成・`step2_summary`・互換 Markdown の `### Step2`）** を別途考えるときは、**[`manga_tag_step2.md`](manga_tag_step2.md)** を必ず併読する（抽象レイアウト・言い換え・主語／レイアウトの最低条件）。長文テンプレやエクスポート仕様は **`docs/image-generation/manga-tag-generation.md`**。
- **エージェント・執筆支援**: ページYAMLの `panels[].prompt_tags` を新規作成・改稿するときは、`.rulesync/skills/manga-prompt-ir/SKILL.md` の「`_how_to/manga_tag.md` との役割分担」に従い、**必ず本ファイルの運用コピー（通常は `_how_to/manga_tag.md`）を開いて**からタグを書く。置き換えリストは **ツールが自動では適用しない**ため、**YAML に明示的に書き込む**まで未完了とみなす。
- **variant の3キー優先・スナップショット・validate**: `manga.md` の「バリアントとタグ注入の優先」節と `tools/novel_prompt_ir_validate.py`。ここでは繰り返さない。
- **`scene` の日本語＋ `location_en` 等**: プロンプト用英語行の運用は従来どおり。ページ組み立ての本体は `manga.md`。
- **保存ファイルの `pNN`**: ページ番号はページYAML**ファイル名**の `_pNN` から（`image_provider_novel_manga_batch.py`）。詳細はルート **`AGENTS.md`** の漫画アセットの節。

コマに載せる意味のチェック（タグ形式より日本語の意味）:

- 誰が写っているか／誰に向けた行為か／どこで／何をしているか／セリフ等の帰属／コマの段・大小・読み順

## 構造化IRとの関係（最小）

`panels[].prompt_tags` に落とす。YAML正本・Step 互換の流れは **`manga.md`**。

- **接写・クローズアップ**: 全身像ではなく**画面に入っている部位・肌・画角**を英語タグで示す方針・`subjects` との役割分けは **`manga.md` の「クローズアップ・接写と `prompt_tags`」** を参照（語彙の例は本ファイルの体位・部位の節と併用）。
- **手と手だけ／キャラYAMLを載せない**: `character_id` 無し・`description_en`／`tag_token` で手の特徴だけ載せる運用は **`manga.md` の「手元・手と手など『キャラID注入を載せない』コマ」** を参照。
- **`manga.genre_tags` / `manga.visual_tags`（ページ共通）**: 互換 Step1 の **各コマ `tag` 行**にページ単位で付く。**フルカラー運用では原則 `monochrome`・`screentone` を入れない**（コマの `prompt_tags` だけ整えても、ここに残ると白黒寄りが毎コマ付き続ける）。詳細は **`manga.md` の「`manga.genre_tags` / `manga.visual_tags`」**。

## 目・視線・表情タグ（コマ用）

**キャラの目の形・色**（`tsurime`, `brown_eyes` 等）は **`world_wear.md` §12** と `tag/characters/*.yaml` の **`000_base`** を正とする。本節は **コマごとに変わる**目元・視線・涙・瞳孔演出の語彙。運用コピーは通常 **`_how_to/manga_tag.md`** に同内容を置く。

### 書き込み先

| フィールド | 用途 |
|-----------|------|
| `panels[].prompt_tags` | **主**。Step1 生成にそのまま乗る英語タグ |
| `panels[].subjects[].pose_action` / `expression_en` | 人物ごとの表情・視線（英語） |
| `composition.focus_en` | 顔アップのとき `yuna's_face`, `hayate's_eyes` など |

- **1コマあたり目関連は 1〜3 タグ**を目安。
- **`000_base` と重複する形タグ**は毎コマに書かない（キャラ YAML から継承）。
- 顔全体のタグ（`blush`, `open_mouth`, `ahegao`）と併用してよい。

### 半目・開き・眠気

| タグ (Danbooru) | 日本語・ニュアンス |
|:---|:---|
| `half-closed_eyes` | 半目 |
| `half_lidded_eyes` | 半目（`half-closed_eyes` と併用しない） |
| `sleepy_eyes` | 眠たそうな目 |
| `wide_eyes` | 見開き（驚き・恐怖） |
| `closed_eyes` | 目を閉じている |

### 印象・性格・感情

| タグ | 日本語（要約） |
|:---|:---|
| `sharp_eyes`, `gentle_eyes`, `kind_eyes` | 鋭い／優しい |
| `seductive_eyes`, `alluring_eyes` | 妖艶 |
| `innocent_eyes`, `smug_eyes`, `mischievous_eyes` | 無邪気／余裕／悪戯 |
| `cold_eyes`, `warm_eyes`, `soft_eyes` | 冷たい／温かい／柔らかい |
| `intense_eyes`, `fierce_eyes`, `sparkling_eyes`, `dull_eyes` | 強い／激しい／キラキラ／鈍い |
| `tired_eyes`, `empty_eyes`, `dead_eyes`, `moist_eyes` | 疲れ／虚ろ／虚無／潤み |
| `glaring`, `disdain`, `sassy_expression` | にらみ／軽蔑／生意気 |
| `mysterious_eyes`, `wise_eyes`, `youthful_eyes`, `mature_eyes` 等 | 雰囲気・年齢印象 |

### 涙・充血・クマ

| タグ | 日本語 |
|:---|:---|
| `tears`, `teary_eyes`, `crying_eyes` | 涙・涙目 |
| `bloodshot_eyes` | 充血 |
| `dark_circles`, `bags_under_eyes` | クマ |

### 視線・ポーズ

| タグ | 日本語 |
|:---|:---|
| `looking_at_viewer`, `looking_away`, `averted_eyes` | こちら／逸らす |
| `sideways_glance`, `upward_glance`, `downward_glance` | 横目／上目／下目 |
| `intimate_gaze`, `piercing_gaze` | 親密／鋭い視線 |
| `one_eye_closed`, `winking`, `rolling_eyes`, `crossed_eyes` | ウィンク／白目／寄り目 |

- 上目遣いは **`upward_glance`**。形タグの `upturned_eyes` と混同しない。

### 瞳孔の一時演出・品質・メイク

| タグ | 用途 |
|:---|:---|
| `heart-shaped_pupils`, `star-shaped_pupils`, `symbol-shaped_pupils` | 記号瞳 |
| `dilated_pupils`, `constricted_pupils` | 瞳孔開閉 |
| `glowing_eyes`, `glowing_pupils` | 一時発光（常時は `000_base`） |
| `beautiful_eyes`, `detailed_eyes`, `eye_reflection` | 描き込み補助 |
| `eyeliner`, `eyeshadow`, `smoky_eyes` | メイク |

固定の目の形は `variant_id` とキャラ継承に任せ、**コマでは変化分だけ** `prompt_tags` に書く。詳細表・YAML 例は **`_how_to/manga_tag.md`** の本節を正とする。

## 眉毛・眉の表情タグ（コマ用）

**眉の太さ・形・手入れ**（`thick_eyebrows`, `arched_eyebrows` 等）は **`world_wear.md` §13** と `tag/characters/*.yaml` の **`000_base`** を正とする。本節は **コマごとに変わる**眉の動き・乱れ・メイク結果の語彙。運用コピーは通常 **`_how_to/manga_tag.md`** に同内容を置く。

### 書き込み先

| フィールド | 用途 |
|-----------|------|
| `panels[].prompt_tags` | **主** |
| `panels[].subjects[].pose_action` / `expression_en` | 例: `furrowed brow`, `raised eyebrows` |
| `composition.focus_en` | 顔アップ |

- **1コマあたり眉関連は 0〜2 タグ**を目安。`000_base` の形タグは毎コマに書かない。

### 眉の動き・感情（要約）

| タグ | 日本語（要約） |
|:---|:---|
| `furrowed_brow` / `furrowed_eyebrows` | ひそめる（併用しない） |
| `raised_eyebrows`, `raised_inner_eyebrows` | 上げる／困り眉 |
| `v-shaped_eyebrows`, `knit_eyebrows` | 八の字／寄せる |
| `twitching_eyebrow`, `drooping_eyebrows` | ピクピク／垂れる |
| `scowl`, `frown` | 不機嫌／しかめ面 |
| `arched_eyebrow`, `smug`, `serious`, `determined`, `disdain` | 片眉上げ／ドヤ／真剣／決意／見下し |

### 乱れ・メイク（§13 から回す状況タグ）

| タグ | 日本語 |
|:---|:---|
| `messy_eyebrows`, `unkempt_eyebrows` | 乱れ／無手入れ |
| `shaved_eyebrows`, `plucked_eyebrows`, `overplucked_eyebrows`, `drawn_eyebrows` | 剃り／抜き／描き足し |

- 詳細表・YAML 例は **`_how_to/manga_tag.md`** の本節を正とする。

## コマ別ネガ（Negative prompt の出し分け）

コマ単位の画像生成（`image_provider_novel_manga_batch.py --source step1-panels`）では、**ネガティブプロンプトは `panels[].prompt_tags`（ポジティブ側のタグ列）には書かない**。次の YAML フィールドと CLI で制御する。

| 指定 | 置き場所 | 役割 |
|------|----------|------|
| `--negative-prompt` | バッチ実行時 | 全コマ共通の**基底**ネガ（未指定時はツール既定の汎用ネガ） |
| `technical.negative_tags` | ページ直下 | そのページの**各コマ**の合成ネガに足す断片 |
| `panels[].negative_tags` | コマごと | **そのコマだけ**に追加する断片 |
| `panels[].omit_negative_tags` | コマごと | 合成の**前**に、基底＋`technical` から**除く**断片（他コマでは残る） |

合成の順序・正本は `.rulesync/skills/manga-prompt-ir/SKILL.md` と `tools/image_provider_novel_manga_batch.py`。

### split screen など「コマによって禁止したい／例外的に許したい」場合

- **方針A（ページで一律禁止し、一部コマだけ例外）**: `technical.negative_tags` に `split screen` 等を載せ、分割画面を意図したコマだけ `omit_negative_tags` に同じ語を列挙して除外する。
- **方針B（デフォルトでは禁止しない）**: `technical` には載せず、分割画面を**避けたい**コマだけ `panels[].negative_tags` に `split screen` を足す。

モデルやプロバイダによって効き方が異なるため、断片の語は生成結果を見ながら調整する。

# 基本的な指示出し
コマごとに場所 (Location),人の状態 (Characters' States),行っているアクション (Actions)などを明確にしてください
登場キャラがいる場合は、**`character.md` と `tag/<romaji>.md` を正として、髪・目・肌・種族・体格・固定小物などの固定特徴を各コマのタグへ継承してください**。
たとえば、
男性が水中で溺れる女性を救助し、抱きかかえている。
という状態を、場所、2人の状態、行っているアクション等を明記した状態でタグにしてください。

underwater scene, swimming pool interior, clear blue water, bubbles floating, dim underwater lighting,
1boy, muscular build, wet clothes, determined expression, short hair,
1girl, slender build, long hair flowing in water, panicked expression, eyes wide open, mouth open gasping for air, soaked dress clinging to body,
boy rescuing girl, boy carrying girl in arms, bridal carry pose, girl clinging to boy desperately, boy swimming upwards with girl,
dynamic action pose, water splashes, sense of urgency, dramatic shadows

# 背景
- 背景のみのシーンの場合はnohumanを入れる

# screentone
screentoneタグがあった場合は除外する

# 効果音を入れる
コマのシーンに入れる場合
sound effects visualization

# 体勢等

- スマートフォンを見ている,ラインの画面別カットで見える
1girl, full color, solo focus , girl gazing at smartphone , she hold smart phone phone, manga panel style intimate close-up, separate inset panel in bottom right showing only glowing blue smartphone screen with LINE messages from friends about shouta, phone back facing viewer

- 新体操やバレエの伸長ポーズ
1girl, solo, standing split, leg lift, flexible, balancing, full body, [hand on leg]

- ｢bent over｣
胴体がほぼ水平になるくらいに深く前かがみになった姿勢。

- ｢hanging breasts｣
キャラクターが前かがみになった時など、乳房が胴体から離れて垂れ下がる事。
また、そうなるくらいの胸の大きさ。

- ｢reaching｣
手を伸ばす動作。

- ｢gyaruo｣
ギャル男。
ギャルの男版。

- ｢undercut｣
ツーブロック。
頭の側面は短く刈り上げ、頭頂部の頭髪は長く残したヘアスタイル。

- ｢eyebrow cut｣
眉毛の一部に剃り込みを入れ、スリットを作るスタイル。

- ｢looking through own legs｣
自分の足の間を通して後ろを覗き見るシチュエーション。
足の間から映す事自体を指すタグは｢view between legs｣。

- ｢groin tendon｣
太ももの付け根のくぼみ。

- ｢hands on ground｣
両方の手を地面に置く場合。

- ｢cramped｣
キャラクターが狭い空間に挟まったり、閉じ込められているシチュエーション。

- ｢trapped｣
閉じ込められた状態から脱出できない状況。
また、そのような厄介な場面。

- ｢struggling｣
なにかに抵抗するキャラクターの反応や表情。

- ｢the pose｣
うつ伏せになり、足を上げたポーズ。
人物の胸、お尻、足を同時に見せるために行われるポーズ。

- ｢invisible floor｣
見えない床。

- ｢head rest｣
頬杖。
手の上に顎を乗せて、頭を支えている場合。

- ｢bath yukata｣
浴衣の一種で、温泉や旅館で着用するタイプのもの。

- ｢shima (pattern)｣
縞模様。
鎖状に描かれる和柄の一種で、おそらく吉原つなぎ文様。

- ｢after bathing｣
キャラクターがお風呂上がりである場合。

- ｢washing another｣
他のキャラクターの体を洗う行為。

- ｢washing back｣
こちらは他のキャラクターの背中を洗う場合。

- ｢hair up｣
本来は長い髪のキャラが髪を上げてまとめている時。

- ｢folded ponytail｣
後ろで折り返したポニーテール。

- ｢doodle inset｣
イラストの中に描かれた落書き。
近い内容のタグに｢sketch inset｣がありますが、落書きの荒さで区別されます。

- ｢multiple expressions｣
表情差分。
同一のキャラクターのさまざまな表情を描いたイラスト。

# 状態
- in bathtub
湯船に入っている場合、in bathtubを追加する。自然に過ごす場合は湯船には座っている等の状態についても考慮する
