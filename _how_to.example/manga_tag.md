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
