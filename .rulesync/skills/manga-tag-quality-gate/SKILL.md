---
name: manga-tag-quality-gate
description: >-
  Manga Tag Mode で manga/pages/*.yaml の漫画ページIRを作成・改稿するときに、
  「誰が」「誰に」「どこで」「何をしているか」「どのセリフが誰のものか」に加え、
  コマ割り・ページレイアウト（コマ数、段・大小、読み順、構図語）と
  background_concepts[]（1ページ最低1件・シーン導入・UI/オブジェクト含む）が明確かを点検する。
  部分アップや身体の一部だけのコマでも意味が読めるように品質ゲートをかける。
  manga/manga_XX.md の Step1 / Step2 は検証後に必要時のみ出す互換出力として扱う。
targets: ["*"]
---

> 横断正本: YAML IR と互換 Markdown の正本・副本関係は **`.rulesync/rules/concepts.md`** の「漫画IRと互換Markdown」を正とする。このスキルは、その正本である `manga/pages/*.yaml` の品質点検に集中する。

## 目的

漫画タグは、絵として雰囲気が出ていても、**主語・相手・行為・セリフの帰属**が抜けると生成結果が破綻しやすい。

本スキルは `manga/pages/*.yaml` の漫画ページIRに対して、

- 誰が写っているか
- 誰と誰の関係か
- 何をしているか
- そのセリフが誰のものか
- 一部アップでも何を意味するカットか
- **1ページを何コマで割るか、段・大小・読み順・構図が追えるか**（レイアウト層）

を最低限読める状態まで整えるための品質ゲートを定義する。

`manga/manga_XX.md` の **Step1 / Step2** は、YAML IR 検証後に `tools/image_provider_novel_manga_batch.py` へ渡すための互換出力である。Manga Tag Mode の初手で Markdown だけを直接作成・修正して完了しない。詳細は **`.rulesync/rules/concepts.md`** の「漫画IRと互換Markdown」を参照する。

本スキルでは、`render_instruction` + `manga` + `panels[]` + `character_snapshots` を合わせた YAML 全体を **Step1相当の作画依頼** とみなし、主語・関係・行為・セリフ・レイアウトが読めるかを点検する。

ただし **コマ生成（`step1-panels`）** は、各コマを1枚の単独画像として出す運用であり、ページ全体のコマ割りタグをそのまま入れない。`japanese manga panel layout`、`horizontal top panel`、`large bottom panel`、`clear panel borders`、`1ページ4コマ`、`上段` / `中段` / `下段` / `大コマ` などはページ生成用の情報であり、コマ単体生成では内部フィルタで落とす。構図として残すのは `close-up`、`medium shot`、`long shot`、被写体、場所、行為、表情、照明などに寄せる。

## 正本・参照

| 参照先 | 用途 |
|--------|------|
| `novels/<作品>/_novel_text/novel_textXX*.md` | 場面・人物・会話・小道具・順序の本文根拠 |
| `novels/<作品>/manga/pages/manga_XX_pYY.yaml` | 点検対象のページ定義正本。`panels[]`・`subjects[]`・`text`・`composition` を検証する。 |
| `novels/<作品>/character.md` | 登場人物の正式名称・関係性・固定設定 |
| `novels/<作品>/tag/characters/<character_id>.yaml` | 外見・状況タグの構造化正本 |
| `novels/<作品>/tag/<romaji>.md` | 外見・状況タグの互換出力・英語タグ参考 |
| `novels/<作品>/manga/manga_XX.md` | 既存バッチ互換出力。移行元・生成直前の確認先であり、正本ではない。 |
| `_how_to/manga.md` | Step1 / Step2 の出力基準 |
| `_how_to/manga_tag.md` | コマの英語タグ・置き換え・NSFW 慣例。`prompt_tags` を埋める前に必ず開く。詳細はスキル **`manga-prompt-ir`** の「`_how_to/manga_tag.md` との役割分担」 |
| `.rulesync/rules/concepts.md` | YAML IR と互換 Markdown の正本・副本関係 |

## `manga.md` を核にした Step1 / Step2（機能の芯と YAML 写像）

品質ゲートで Step1・Step2 を点検するときは、**まず `_how_to/manga.md` を開き**、同ファイル内の **互換出力: step1**（および冒頭の IR 説明）・**互換出力: step2** を正として読む。リポジトリの雛形は **`_how_to.example/manga.md`**。ユーザーが `_how_to/manga.md` をカスタムしている場合は **そちらを優先**する。

### 役割の芯（`manga.md` の定義に沿う）

| モード | 何のためか（要約） | `manga.md` で読む節 |
|--------|-------------------|---------------------|
| **Step1 相当** | コマ単位の**具体的な作画・タグ**（コマ生成・精密ページ生成の入力） | **互換出力: step1**、および [`docs/image-generation/manga-prompt-ir.md` のページ YAML 最小例節](../../docs/image-generation/manga-prompt-ir.md#yaml-minimal-step1)・**POV・接写**・**variant** |
| **Step2 相当** | **ページ丸ごと生成**向け。抽象度を上げつつ、**誰がどこにいるか・段・大小・読み順**が追える**配置語**で書く。強い行為名は**構図・視線・距離**へ言い換え（モデレーション配慮） | **互換出力: step2**（「行為を構図に言い換える」「抽象名詞だけで終えない」等） |

### YAML IR への写像（点検するときの着手場所）

| `manga.md` 上の意図 | 主に見る YAML |
|---------------------|----------------|
| Step1：各コマの見出し・具体描写 | `panels[].summary`, `panels[].subjects[]`, `panels[].composition`, `panels[].camera`, `panels[].text`, `panels[].prompt_tags` |
| Step1：コマ要約の英訳（NovelAI タグ併用） | **`panels[].summary_en`**（`tools/novel_manga_panel_summary_en.py` で `summary` から生成）、**`summary_en_source`** が `summary` と一致 |
| Step1：ページ全体の作画方針・コマ割の扱い | `render_instruction`（`task` / `prompt_header` / `panel_policy` / `character_policy`）、`manga.panel_layout` |
| Step2：段・左右・大小・読み順 | `manga.panel_layout`, `meta.reading_order`, `panels[].composition.layout`（互換 Markdown では1行に畳まれる） |
| Step2：コマ要約（抽象寄り・安全寄りの言い換え） | **`panels[].step2_summary` を優先**（無ければ `summary` が Step2 行に流用される。`manga.md` の「Step2 だけ弱めたい」と同じ） |
| 固定外見を Step2 本文に毎回書かない | `character_snapshots[]` と `tag/characters/*.yaml`（互換出力の【固定見た目】はツールが合成） |

**英語タグの語彙**は `manga.md` ではなく **`manga_tag.md`**。本スキルの §1〜§5 と上表を併用する。

## 使う場面

- `manga_page.yaml` を新規作成・改稿した直後
- `manga/pages/*.yaml` から互換 Markdown を出力する直前
- 既存の `step1` / `step2` を YAML へ移行するとき
- 画像生成前に「意味が落ちていないか」を見直したいとき

## 品質ゲート

### 1. 主語の明示

各コマで、最低でも **誰が写っているか** を読めるようにする。

- `和紀の手元` のように、**部位だけのカットでも所有者を明示**する
- `誰かの手`, `人物の横顔` のような曖昧語で終わらせない
- YAML では `panels[].subjects[]` に最低1件入れ、人物なら `character_id` を付ける

### 2. 関係の明示

二人以上が出るコマは、**誰と誰がどういう位置関係か** を書く。

- 例: `和紀がエルへスマホ画面を見せる`
- 例: `エルが和紀の右後方から声をかける`

### 3. 行為の明示

各コマで **何をしている瞬間か** を動詞で書く。

- `見ている`
- `差し出す`
- `触れる`
- `振り向く`
- `説明する`

雰囲気語だけで終わらせない。

### 4. セリフ帰属の明示

セリフがあるコマは、**誰のセリフか** が分かるようにする。

- Step1 では、セリフの前後どちらでもよいので話者が読める文脈を置く
- Step2 では、吹き出しを置く想定がある場合は **どの人物の発話か** を構図説明側で分かるようにする
- YAML では `text.dialogue[].speaker` を必須にし、モノローグ・ナレーション・効果音と混ぜない

### 5. 部分アップの意味付け

手・足・口元・スマホ画面・目元など、**一部だけのコマ**は次を補う。

- 誰の部位か
- 何のためのカットか
- 何を見せたいか

例:

- 悪い例: `スマホ画面のアップ`
- 良い例: `和紀のスマホ画面アップ。見覚えのない DivineQA アプリと β 印を見せる情報提示カット`

### 6. Step1（`_how_to/manga.md` の **互換出力: step1** に準拠）

点検のたびに **`_how_to/manga.md` を開き**、**「互換出力: step1」** 節を正として読む（雛形・正本の参照用は **`_how_to.example/manga.md`** の同節）。

**この節で足りること（スキル側の要約）**

- **1コマ1意味**: 各コマが単独画像になっても通じるよう、同節の箇条書き（誰が・誰に・どこで・何をしている瞬間か・セリフの話者・見せたい情報・向き・アングル・服装・小道具・部分アップの補足・曖昧語禁止）を満たすか。
- **コマと英語タグの対応**: **1コマにつき1つの `tag:` ブロック**（複数コマを1タグにまとめない）。英語タグの語彙は **`manga_tag.md`**。
- **レイアウト**: 同ファイル内 **「コマのページ内位置（レイアウト）を明記する」** に従い、**(A) `### Step1` 直後のページ配置1行** または **(B) 各 `コマN:` 先頭の段・大致** のどちらかを満たす。コマ単体生成だけでも入れておくと、後から精密ページ化したときにブレにくい。
- **日本の漫画のコマ割り**をページ方針として一度は明示する。**不要なら** 英語タグに `vertical` / `horizontal` 等を機械的に足さない（`manga.md` と同じ）。

**YAML 原盤で見る場所**（上記と齟齬がないか）

- コマ本文・具体度: `panels[].summary`, `panels[].subjects[]`, `panels[].composition`, `panels[].camera`, `panels[].text`, `panels[].prompt_tags`
- ページ方針・コマ順: `render_instruction`（`prompt_header` / `panel_policy` 等）、`manga.panel_layout`

### 7. 背景概念（`background_concepts[]`）

**目的**: コマタグだけでは、舞台・光・反復する UI／小道具の参照が弱く、`background-concepts` 生成に渡す材料が無いまま画像生成に進みやすい。Manga Tag Mode の完了条件の一部とする。

**この節で足りること**

- **1ページ最低1件**の `background_concepts[]` があるか（未記載・`[]` のみは NG）。
- **シーン・場所の最初のページ**では、読者に空間を見せる **establishing / wide** 系が **1件以上** あるか。
- **「背景」カテゴリだけに限定しない**。執筆 UI、実験机、窓と外景など、ページで繰り返す **オブジェクト** も `concept_id` / `prompt` で切り出されているか。
- 重要な `subjects[]`（`type: object` 等）が、コマだけでなく背景概念にも載っているか（一貫性）。
- 各件の `prompt` が英語で、人物なしの背景資料として読めるか。`negative_tags` に `people` 等があるか。

**YAML で見る場所**

- `background_concepts[]`（`scene` と併せて舞台の英語 `*_en` が揃っているかも確認）
- 再利用のみのページは `_meta.md` または `render_instruction.user_directives.page_notes` に再利用メモがあるか

**典型的な不足（失敗パターン）**

- `panels[]` のみ完成し、`background_concepts` が無い（064 プロローグ初回のような取りこぼし）。
- 室内全景はあるが、**ページの核になる UI や小道具**（例: エディター画面）がコマ subject だけで背景概念に無い。

詳細・生成コマンドはスキル **`manga-prompt-ir`** の「`background_concepts[]`（Manga Tag Mode）」を正とする。

### 8. Step2（`_how_to/manga.md` の **互換出力: step2** に準拠）

点検のたびに **`_how_to/manga.md` を開き**、**「互換出力: step2」** 節を正として読む（雛形は **`_how_to.example/manga.md`** の同節）。

**この節で足りること（スキル側の要約）**

- **ページ内位置**: 各コマについて **上段／中段／下段・左右・大ゴマ／小コマ・横並び** が読めるか。均等な縦Nコマだけなら **`均等Nコマ・上から読む` の一行**でよい（`manga.md` と同じ）。
- **抽象化の下限**: **誰が主役か・誰と誰の関係か・コマの役割・セリフがあるなら誰の発話か**が消えないこと。部分アップは **部位と意味**を短く添える。
- **抽象名詞で終わらない** / **行為を消すのではなく構図に言い換える** / **モデレーション配慮の言い換え**は、**悪い例・良い例・言い換え目安**まで **`manga.md` の step2 節に従う**（本スキル §1〜§5 と重なる主語・帰属はそちらも併用）。
- **互換 Markdown の形**: エクスポートは `novel_prompt_ir_export_md.py` が **`manga.panel_layout`・`meta.reading_order`・`panels[].composition.layout`・`step2_summary`（無ければ `summary`）** から組み立てる。Step2 だけ弱めたいときは IR に **`panels[].step2_summary`** を置き、**`summary` は Step1（コマ生成）向けに具体のまま**残せる（`manga.md` の「互換 Markdown の Step2」節と同じ）。

### 9. レイアウト・読み順（Step1 / Step2 横断の確認）

**目的**: ページ丸ごと生成（`step2-pages`）や精密ページ生成（`step1-pages`）では、**コマ境界と読み順**が無いと「ただのカット列」になりやすい。細部の書き方の正本は引き続き **`manga.md` の「コマのページ内位置（レイアウト）を明記する」** および **step1 / step2 の出力例**。

**YAML で追加確認**

- `render_instruction.prompt_header` / `panel_policy` に、ページ全体の作画依頼とコマ割りの扱いがあるか。
- `manga.panel_layout` と `meta.reading_order` が、互換 Step2 の1行目（`1ページ{N}コマ。…読み順は …`）と矛盾しないか。
- 各 `panels[].composition.layout` が、段・左右・大小・読み順を追えるか（空のまま列挙だけになっていないか）。

**典型的な不足（失敗パターン）**

- Step2（または `step2_summary`）に **コマ番号だけ**あり、**段・大小が一切無い**。
- Step1 相当で **コマ数・コマ割り宣言が無く**、`panel_id` 列だけ並んでいる。

### 10. 色モード（モノクロ／限定色／カラー）の確認

**目的**: `color_palette.mode` と `manga.visual_tags`、`render_instruction` の方向が食い違うと、互換 Markdown やページ生成プロンプトの冒頭文だけがカラー／モノクロに寄ってしまう。ページYAMLの `color_palette.mode` を正本とし、矛盾は `novel_prompt_ir_validate.py` の **WARNING** で確認する。

**YAML で追加確認**

- `color_palette.mode` が `monochrome` / `limited_color` / `full_color` のどれかとして意図どおりか。
- `manga.visual_tags` / `manga.genre_tags` / `panels[].prompt_tags` に、モードと逆向きのタグが混ざっていないか。
- `render_instruction.prompt_header` 等に「カラー」「モノクロ」など、モードと逆向きの文言が残っていないか。
- センターカラー、巻頭カラー、扉絵だけカラー、一部コマだけ限定色などの例外は、WARNING を確認したうえで意図的に残してよい。通常運用では自動修正・通常エラー化しない。

## 改稿手順

1. **`_how_to/manga.md` の「互換出力: step1」「互換出力: step2」** を開き、上記 §6・§7・§8 の要約と照合できる状態にする。§7（背景概念）とスキル **`manga-prompt-ir`** の `background_concepts[]` 節も満たす。
2. 対象の小説本文と `manga/pages/*.yaml` の各 Page を上から読む。
3. コマごとに §1〜§5（主語・関係・行為・セリフ・部分アップ）を確認する。
4. §6（step1 準拠）で具体度・1コマ1タグ・レイアウト入口を確認する。
5. §7（step2 準拠）で抽象化の下限・段・大小・`step2_summary` の有無を確認する。
6. §8 で `panel_layout` / `reading_order` / `composition.layout` を確認する。
7. §9 で色モードとタグ・作画指示の矛盾 WARNING を確認する。
8. 欠けた要素を、冗長にしすぎない範囲で YAML 正本に補う（互換 Markdown は再エクスポート）。
9. YAML の `panels[].text.dialogue[]` / `narration` / `monologue` / `sfx` が混線していないか最終確認する。
10. 互換 Markdown の直接修正で終えず、YAML 正本へ戻したかを確認する（詳細は `concepts.md`）。

## 禁止事項

- 雰囲気だけで主語を失ったままにしない
- YAML があるのに、Markdown の Step1 / Step2 だけを直接新規作成・修正して正本扱いしない
- 部位カットを、所有者不明のまま置かない
- セリフを、誰が話しているか不明のまま置かない
- Step2 の抽象化を理由に、人物関係やコマの意味まで削らない
- Step2 を `接触` `忍耐` のような抽象名詞の羅列にしない
- **ページ生成・ページ丸ごと生成を前提にしつつ**、Step2 に **コマの段位置や大小が一切無い**（読み手が枠を再構成できない）ままにしない

## チェック用の短い問い

各コマについて、次にすべて即答できるかを見る。

- 誰が写っているか
- 何をしているか
- 誰に向けた動きか
- どこで起きているか
- セリフは誰のものか
- このコマは何を伝える役割か

**レイアウト（ページ単位で追加）**

- このページは **何コマ構成か**（Step1 先頭の宣言またはコマ番号の最大で確定できるか）
- Step2 だけを読んだとき、**どのコマが大きく／どの段に置かれるか** が想像できるか（均等割なら「上から順に4コマ」など一言でよい）
- 読み順（上→下、左→右）は迷わないか

1つでも即答できないなら、そのコマ（またはページの Step1/Step2 宣言）は追記対象。

## 関連

- スキル `manga-tag-character-sync`
- ルール `.rulesync/rules/overview.md` の Manga Tag Mode
- 画像生成スキル `image-provider（旧 forge-txt2img）`
