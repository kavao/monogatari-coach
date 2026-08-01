# 指示出しベースのワークフロー（ユーザー視点）

このページを読むと、Monogatari Coach にチャットで何をどう指示すれば制作が進むかがわかります。

各指示は**一言で動くように内部でルール化**されています。長いテンプレートは「より詳しく指定したいとき」の補足です。

各操作の「**使われるツール**」欄は、Monogatari Coach が内部で呼び出す CLI コマンドです。手動でも実行できます（`※ 自動呼び出し` と書いたものも含む）。

詳細な仕様（`.rulesync/`）を読まなくても、まずはこのページの導線で動かせることを目的にしています。

---

## 操作一覧

**初回導入**:
[1. 状態確認](#1-状態確認) /
[2. 新規作品を始める](#2-新規作品を一から始める) /
[3. 既存資料を取り込む](#3-既存資料を取り込んで展開する) /
[4. 執筆を再開する](#4-執筆を再開するセッション再開)

**制作フロー**:
[A. 企画・設計](#a-企画設計を固める) /
[A'. チャットモード](#a-チャットモードで始める対話型執筆--trpg) /
[B. 執筆](#b-執筆する) /
[C. 清書・校正](#c-清書文章校正する) /
[D. 下読み](#d-下読き足きり判定する) /
[D2. Editor Score](#d2-完稿推敲後に深掘り採点するeditor-score) /
[D3. Consistency Audit](#d3-設定口調の一貫性を監査するconsistency-audit) /
[E. 興味判定](#e-一般読者視点で興味を判定する) /
[F. メタ情報更新](#f-メタ情報を更新する)

**画像生成（任意）**:
[G. キャラタグ作成](#g-キャラクター画像タグを作るtag-mode) /
[H. キャラ画像生成](#h-キャラクター画像を生成する) /
[I. 漫画タグ作成](#i-漫画ページタグを作るmanga-tag-mode) /
[J. 漫画画像生成](#j-漫画画像を生成する) /
[K-1. 挿絵計画](#k-1-挿絵計画を作るillustration-plan-mode) /
[K-2. 挿絵IR作成](#k-2-挿絵表紙の-ir-を作るillustration-tag-mode) /
[L. 挿絵生成](#l-挿絵表紙を生成する) /
[L-2. 表紙合成・題字](#l-2-表紙合成題字ロゴcover-composition) /
[L-3. 出版 proof](#l-3-出版パッケージと-proof-pdf) /
[M. 背景資料生成](#m-背景画像背景資料を生成する)

---

## 初回導入

> **チャットモード（対話型・TRPG）** を使いたい場合は [チャットモード](chat-writing-mode.md) も参照してください。会話しながらゲートを刻んで進めるワークフローと、TRPG セッション形式でパラメータを追跡しながら小説にする方法を説明しています。

### 1. 状態確認

```text
初回導入の設定をしてください。
```

**このように動きます:**
1. リポジトリの初期化状態（`.env`・`rulesync` 生成物の有無）を確認する
2. 不足があれば「次に実行するコマンド」「`.env` に埋めるべきキー」を一覧で提示する
3. 問題がなければそのまま制作の目的確認へ進む

API キーの取得先は [Image Generation](../image-generation/index.md#api-キーの取得先) を参照してください。

**使われるツール:**

```bash
# リポジトリ取得
git clone https://github.com/kavao/monocri.git
cd monocri

# Python 依存関係と .venv を作成
uv sync

# 初回セットアップ（_how_to/ と .env を未作成時にコピー）
uv run python howto_init.py

# 初回のみ: 固定版 Rulesync を取得
python tools/install_rulesync.py

# ルール・スキルの生成物を同期
python tools/rulesync.py generate

# .env の不足確認
python tools/env_check.py
```

---

### 2. 新規作品を一から始める

```text
新規作品を始めたいです。
```

**このように動きます:**
1. 作品名・ジャンル・ログライン・主人公について必要最低限の質問をする
2. `novels/NNN_作品名/` フォルダを作成し、`proposal.md` / `design_specification.md` / `config.md` / `character.md` / `world.md` を生成する
3. 生成した内容を評価・洗練して、執筆できる状態まで整える
4. 次のステップ（執筆・タグ作成など）を提案する

より詳しく情報を渡したいときは以下のように補足できます。

```text
新規作品を始めたいです。
- 作品名：
- ジャンル／テイスト：
- ログライン（1〜2文）：
- 主人公（仮でOK）：
```

**使われるツール:**

```bash
# novel_code（作品番号）の採番・検証 ※ 自動呼び出し
python tools/novel_code_allocate.py novels/

# 必須ファイルの揃いを確認 ※ 自動呼び出し
python tools/novel_project_check.py novels/NNN_作品名
```

---

### 3. 既存資料を取り込んで展開する

```text
source_material の資料を元に作品を展開してください。
```

**このように動きます:**
1. `source_material/` または `novels/_import/` 配下のファイルをすべて読む
2. プロット・人物・世界観・本文の下書きを Monogatari Coach の形式（`proposal.md` 等）に対応付ける
3. `novels/NNN_作品名/` に展開し、原資料は `_source_material/` に参照用として退避する
4. 既存の `novels/` に同一作品がある場合はバックアップを作ってから差分更新する

**使われるツール:**

```bash
# novel_code の採番 ※ 自動呼び出し
python tools/novel_code_allocate.py novels/
```

詳しい保存先と原資料の保全ルールは [Source Material Intake](source-material-intake.md) を参照してください。

---

### 4. 執筆を再開する（セッション再開）

```text
作品を再開してください。
```

**このように動きます:**
1. `novels/<作品>/_meta.md` を読んで前回の進捗・未回収の伏線・次のタスクを復元する
2. 現在の状態と「次に何をすべきか」をチャットで報告する
3. そのまま続きの作業へ移行できる

---

## 制作フロー（基本操作）

### A. 企画・設計を固める

```text
企画書と設計書を作ってください。
```

**このように動きます:**
1. `proposal.md`（作品名・ログライン・あらすじ・キャラ紹介）を生成する
2. `design_specification.md`（テーマ・章構成・ストーリー相関図）を生成する
3. 設計の不備を自己評価し、ストーリーを洗練させる
4. 執筆前に必須ファイルの揃いを確認する

**使われるツール:**

```bash
# 必須ファイル・ディレクトリの揃いを確認 ※ 自動呼び出し
python tools/novel_project_check.py novels/NNN_作品名

# Tag Mode 済みも必須にする場合
python tools/novel_project_check.py novels/NNN_作品名 --require-tag

# 漫画フォルダまで揃えたい場合
python tools/novel_project_check.py novels/NNN_作品名 --require-manga-dir
```

企画・設計フェーズの詳しい確認観点は [Planning](planning.md) を参照してください。

---

### B. 執筆する

```text
第1章を執筆してください。
```

**このように動きます:**
1. `writer_profile.md` を参照して作家の文体を確認する
2. `proposal.md` / `design_specification.md` / `character.md` / `world.md` を参照する
3. `novels/<作品>/_novel_text/novel_text01.md` に本文を書き出す（4000〜8000字目安）
4. 書き終えたら `tools/novel_char_count.py` で文字数を集計して報告する

章・項を指定する場合は以下のように補足できます。

```text
第2章の前半を執筆してください。
```

**使われるツール:**

```bash
# 事前確認: 必須ファイルの揃い ※ 自動呼び出し
python tools/novel_project_check.py novels/NNN_作品名

# 執筆後: 文字数の集計（章別・合計） ※ 自動呼び出し
python tools/novel_char_count.py novels/NNN_作品名

# 特定ファイルのみ確認する場合
python tools/novel_char_count.py novels/NNN_作品名/_novel_text/novel_text01.md
```

---

### C. 清書・文章校正する

```text
第1章を清書してください。
```

**このように動きます:**
1. `_novel_text_backup/` に元ファイルを `novel_text01_v001.md` 形式で退避する
2. `_how_to/rewrite.md` のルールを適用して文章を磨き上げる（1.5倍程度の分量が目安）
3. `novels/<作品>/_novel_text/novel_text01.md` を上書き保存する
4. 校正前後の文字数を比較して報告する

**使われるツール:**

```bash
# 校正前後の文字数を集計して比較 ※ 自動呼び出し
python tools/novel_char_count.py novels/NNN_作品名
```

---

### D. 下読み（足切り判定）する

最小のトリガー文1行で動きます。

```text
第1章を足切り判定してください。
```

段階を指定したい場合は、以下のように書き分けます。

```text
# G1: 冒頭（〜3,000字）だけで速断する
第1章をG1足切りしてください。

# G2: 1章完で判定する
第2章をG2章完足切りで判定してください。

# G3: 全文で判定する
全章をG3全文足切りで判定してください。

# Interest Check と組み合わせる
Interest Check のあと、第1章をG1足切りしてください。
```

**このように動きます:**
1. `config.md`・対象 `_novel_text/*.md`・文字数（`novel_char_count.py`）を確認する
2. `_how_to/reader.md` の6項目100点採点（冒頭の牽引力/キャラクター/プロット期待値/文章力/わかりやすさ/独創性）で評価する
3. 70点以上: 読むべき / 55〜69点: 強い美点1つ以上なら読むべき / 54点以下: 読まなくていい — の閾値で足切りを判定する
4. 結果を `novels/<作品>/_reader/YYYYMMDD_HHMM.md` に保存する
5. チャットには判定・総合点・改善ポイント要約・保存先パスだけを返す

詳しい保存先・閾値・ゲート段階の説明は [Reader Output](reader-output.md) を参照してください。

評価を始める前に章別文字数と既存評価を確認したい場合は、以下のコマンドが使えます。

```bash
# 評価準備情報・frontmatter テンプレを表示する
python tools/novel_evaluation_prepare.py novels/NNN_作品名 --gate G2

# 過去の評価スコア推移を確認する
python tools/novel_evaluation_diff.py novels/NNN_作品名
```

*（評価の採点自体は LLM が直���処理します。CLI ツールは準備・確認用です）*

---

### D2. 完稿・推敲後に深掘り採点する（Editor Score）

足切り通過後の作品を、「どこを直すと何点上がるか」の観点で採点します。

```text
全文をEditor Scoreで採点してください。
```

長文の場合はあらすじを先行させます。

```text
あらすじを作成してから、Editor Scoreで採点してください。
```

**このように動きます:**
1. 足切り済みであることを確認する（`_reader/YYYYMMDD_HHMM.md` の判定が「読むべき」）
2. `config.md`・`character.md`・`world.md`・`design_specification.md` を参照する
3. `_how_to/editor_score.md` の5項目100点（構造/キャラ/文体/世界観/完成度）で採点する
4. 結果を `novels/<作品>/_reader/score_YYYYMMDD_HHMM.md` に保存する
5. チャットには総合点・致命的弱点件数・保存先パスだけを返す

詳しい手順は [Reader Output](reader-output.md) を参照してください。

*（足切り用の reader.md とは別ファイル・別配点です。混同しないでください）*

---

### D3. 設定・口調の一貫性を監査する（Consistency Audit）

複数章完成後に、設定矛盾・口調のブレ・未回収伏線を洗い出します。

```text
第1〜3章の設定・口調の一貫性を監査してください。
```

**このように動きます:**
1. `_novel_text/*.md`・`character.md`・`world.md`・`design_specification.md` を参照する
2. `_how_to/consistency_audit.md` の観点で章横断の矛盾・揺れを洗い出す
3. 結果を `novels/<作品>/_reader/consistency_YYYYMMDD.md` に表形式で保存する
4. チャットには矛盾件数の内訳（矛盾/要確認/軽微）と保存先パスだけを返す

詳しい手順は [Reader Output](reader-output.md) を参照してください。

---

### E. 一般読者視点で興味を判定する

```text
第1章を一般読者の視点で興味判定してください。
```

**このように動きます:**
1. `_how_to/standard_reader.md` からペルソナを設定する
2. タイトル・冒頭3行・最初の1ページで「読み続けるか・離脱するか」を判定する
3. 結果を `novels/<作品>/_reader/interest_YYYYMMDD.md` に保存する
4. チャットには「継続 / 離脱」の判定と決め手を1〜3行で返す

詳しい保存先と手順は [Reader Output](reader-output.md) を参照してください。

*（このモードは LLM が直接処理するため、CLI ツールは使いません）*

---

### F. メタ情報を更新する

```text
メタ情報を更新してください。
```

**このように動きます:**
1. `_how_to/meta.md` のフォーマットに従い、`novels/<作品>/_meta.md` を更新する
2. 現在の進捗・未回収の伏線・次回タスクを明文化する
3. 外部投稿（カクヨム等）向けの紹介文が必要な場合はそれも生成する

執筆の切り上げ時に「メタを更新してください」と一言入れるだけで引き継ぎ情報が揃います。

**使われるツール:**

```bash
# 査証ログ（セッションの作業記録）を追記 ※ 自動呼び出し
python tools/workspace_audit_log.py append "作業内容"

# 横断ナレッジ日記を追記 ※ 自動呼び出し
python tools/workspace_audit_log.py diary append "学びや判断の記録"
```

---

## 画像生成（任意）

画像タグ、漫画ページ、挿絵・表紙は、本文が進んだ段階で別モードとして動かせます。画像生成は必ず `--dry-run` で計画を確認し、ユーザーの承認を受けてから本番実行します。

### G. キャラクター画像タグを作る（Tag Mode）

```text
プロフィールからタグを作成してください。
```

これだけ入力しても Monogatari Coach は Tag Mode を開始します。

**正本（必須 ID・汎用／カスタムの分離）:** [ワークフロー詳細仕様](../../.rulesync/rules/workflow-specification.md) の「Tag Mode バリアント階層」「Tag Mode 汎用テンプレートとカスタム要素」「Tag Mode 作品メタ」「Tag Mode テンプレート一式」。**創作技法（任意）:** `_how_to/tag.md`（Danbooru 語彙・`outfit_tags` 混入など）。

**バリアントの3層（主要キャラごと）**

| 帯 | 例 | 漫画で使うか |
|----|-----|----------------|
| `000_base` | 固定外見のみ | いいえ |
| **000番台** | `001_normal`（平服）、治療服、水着 等 | **はい**（`variant_id`） |
| **100番台（汎用）** | `100_intro`、`101_turnaround`、`102_signature_pose` | いいえ（参照画像用。`combines_with` で000番台と合成） |
| **カスタム** | 作品が `_meta.md` に列挙した ID のみ（例: 資料・特殊衣装） | 帯は 000 または 100。共有マニュアルでは具体 ID を固定しない |

000番台だけ作って終わりにせず、**汎用100番台まで YAML に書く**のが標準です。省略するときは理由を `description` または作品 `_meta.md` のキャラタグ方針に残します。

**このように動きます:**
1. `character.md` を読んで外見・服装・固定特徴を把握する（初版は `_how_to/world_wear.md` を参照してよい）
2. `tag/characters/<character_id>.yaml` に YAML IR を作成する（`000_base` → 000番台 → 100番台の順、`combines_with` 付き）
3. `novel_prompt_ir_validate.py` で検証する
4. `tag/<romaji>.md` に **`--novelai-pipe-tags`** 付きで互換 Markdown を出力する（100番台は `資料タグ | 000番台タグ` 形式）

**使われるツール:**

```bash
# 画像保存先フォルダを一括作成 ※ 自動呼び出し
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# YAML IR 検証
python tools/novel_prompt_ir_validate.py novels/NNN_作品名

# YAML IR → 互換 Markdown へエクスポート（100番台のパイプ形式を含む）
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --output-dir novels/NNN_作品名 \
  --novelai-pipe-tags
```

**テンプレート一式（汎用 ID を AI 判断で省略しない）:**

```text
Tag Mode（テンプレート一式）でお願いします。
```

ワークフロー詳細仕様の「Tag Mode テンプレート一式」に従い、主要キャラごとに次を書きます。**カスタムはテンプレート一式だけでは追加されません**（作品メタに列挙した分のみ）。

| 対象 | 内容 |
|------|------|
| 必ず（汎用） | `000_base`、`100_intro`、`101_turnaround`、`102_signature_pose`（`combines_with` 付き） |
| 000番台 | `_meta.md` §4（漫画 variant 表）の `variant_id` をすべて YAML に揃える |
| カスタム | `_meta.md` **キャラタグ方針**の **カスタム要素** に列挙した ID のみ |

作品ごとに常時テンプレート一式にする場合は、`_meta.md` のキャラタグ方針で **バリアント方針: テンプレート一式** と書く（フィールド定義はワークフロー詳細仕様「Tag Mode 作品メタ」。記載例: `_how_to.example/meta.md` §6）。除外する ID があるときだけチャットで列挙する。

**より詳細に指定したい場合（コピペ用）:**

```text
Tag Mode: novels/NNN_作品名。ワークフロー詳細仕様の汎用テンプレートに従い、
主要キャラ全員で 000_base → 000番台 → 100番台（100_intro, 101_turnaround,
102_signature_pose、combines_with 付き）を tag/characters/*.yaml に作成。
カスタムは _meta.md キャラタグ方針のカスタム要素列挙分のみ。
--novelai-pipe-tags で tag/<romaji>.md を出力。
```

```text
Tag Mode（テンプレート一式）: novels/NNN_作品名。
ワークフロー詳細仕様「Tag Mode テンプレート一式」に従い、汎用 ID と _meta.md §4 の 000番台を
tag/characters/*.yaml に揃え、--novelai-pipe-tags で MD 出力。
カスタムは _meta.md のカスタム要素列挙分のみ。除外 ID だけチャットで列挙。
```

---

### H. キャラクター画像を生成する

```text
キャラクター画像を生成してください。
```

**このように動きます:**
1. `.env` のプロバイダ設定を確認する
2. `--dry-run` でプロバイダ名・ジョブ数・保存先をチャットに提示する
3. ユーザーの「OK」を受けてから本番実行する（承認なしには実行しない）
4. `novels/<作品>/tag/<romaji>/` に画像が保存されたことを確認して報告する

**使われるツール:**

```bash
# 確認（dry-run）— provider・ジョブ数・保存先を表示する
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名 --dry-run

# 本番実行（「OK」を確認してから）
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名
```

---

### I. 漫画ページタグを作る（Manga Tag Mode）

```text
本文から漫画タグを作成してください。
```

**このように動きます:**
1. 本文と `tag/characters/*.yaml` の固定特徴を参照する
2. `manga/pages/manga_XX_pYY.yaml` にページ定義を作成する
3. `tools/novel_prompt_ir_validate.py` で型・品質を検証する
4. 必要なら `manga/manga_XX.md` に互換 Markdown を出力する

詳細は [manga-prompt-ir.md](../image-generation/manga-prompt-ir.md) を参照。

**使われるツール:**

```bash
# キャラ外見をページ YAML に埋め込む ※ 自動呼び出し
python tools/novel_prompt_ir_embed_snapshots.py novels/NNN_作品名

# 型・参照・品質の検証 ※ 自動呼び出し
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality

# YAML IR → 互換 Markdown へエクスポート ※ 自動呼び出し
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml \
  --output-dir novels/NNN_作品名 --manga-stem manga_01 --novelai-pipe-tags

# Step2 の言い換え表を反映してエクスポートする場合
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml \
  --output-dir novels/NNN_作品名 --manga-stem manga_01 --step2-paraphrase

# 漫画画像フォルダを一括作成 ※ 自動呼び出し
python tools/novel_image_layout.py scaffold novels/NNN_作品名 --panels 4
```

---

### J. 漫画画像を生成する

コマ単位（パネルごとに1枚）:

```text
漫画コマを生成してください。
```

ページ単位（1ページ丸ごと1枚）:

```text
漫画ページを生成してください。
```

**このように動きます（いずれも共通）:**
1. `.env` のプロバイダ設定を確認する
2. `--dry-run` でプロバイダ名・ジョブ数・保存先をチャットに提示する
3. ユーザーの「OK」を受けてから本番実行する（承認なしには実行しない）
4. `novels/<作品>/manga/_assets/<manga_XX>/comic/` に画像が保存されたことを確認して報告する

**使われるツール:**

```bash
# コマ生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels --dry-run

# コマ生成（本番）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels

# ページ生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --dry-run

# ページ生成（dry-run / Step2 言い換え表を適用）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --step2-paraphrase --dry-run

# ページ生成（本番）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait
```

---

### K-1. 挿絵計画を作る（Illustration Plan Mode）

```text
挿絵計画を作成してください。
```

表紙計画を作りたい場合:

```text
表紙計画を作成してください。
```

**このように動きます:**
1. `_meta.md` §3〜§3.2 を読み、章ごとの枚数・位置・優先シーンを確認する
2. 章ごとに候補場面3点を挙げ、採用・本文アンカー・衣装 variant を決める
3. `illustrations/plans/chapter_plan.md`（または `cover_plan.md`）に記録する
4. `_meta.md` §3.2 の「計画」列を `済` にする

詳細は [挿絵 IR](../image-generation/illustration-prompt-ir.md) の「二段パイプラインの概要」を参照。

**使われるツール:**

```bash
# 計画フォルダの作成（自動呼び出し）
python tools/novel_image_layout.py scaffold novels/NNN_作品名
```

---

### K-2. 挿絵・表紙の IR を作る（Illustration Tag Mode）

Step 1（K-1）の計画 MD で採用が確定した章のみ実行します。

```text
本文から挿絵タグを作成してください。
```

表紙を作りたい場合:

```text
この作品の表紙IRを作成してください。
```

**このように動きます:**
1. `_meta.md` §3.2 と `illustrations/plans/chapter_plan.md` を読み、採用済みの IR を確認する
2. 本文と `tag/characters/*.yaml` の固定特徴を参照する
3. 採用分のみ `illustrations/pages/illustration_XX_pYY.yaml` に YAML IR を作成する
4. `meta.intent: illustration` として、漫画ではない一枚絵の作画依頼にする
5. `tools/novel_prompt_ir_validate.py` で型・品質を検証する

詳細は [挿絵 IR](../image-generation/illustration-prompt-ir.md) を参照。

**使われるツール:**

```bash
# 画像保存先フォルダを一括作成 ※ 自動呼び出し
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# 型・参照・品質の検証 ※ 自動呼び出し
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality
```

---

### L. 挿絵・表紙を生成する

```text
挿絵を生成してください。
```

表紙の場合:

```text
表紙を生成してください。
```

**このように動きます:**
1. `.env` の `MONOCRI_ILLUSTRATION_*` 設定を確認する
2. provider 別 prompt formatter でプロンプト形式を整える
3. `--dry-run` でプロバイダ名・プロンプト・保存先をチャットに提示する
4. ユーザーの「OK」を受けてから本番実行する（承認なしには実行しない）
5. `novels/<作品>/illustrations/_assets/<illustration_XX>/` に画像が保存されたことを確認して報告する

Grok / OpenAI / OpenRouter 系では、`negative_prompt` を API に直接渡さず `Do not include:` セクションへ統合します。比較したい場合は `--prompt-formatter` で一時上書きできます。

**使われるツール:**

```bash
# 挿絵・表紙生成（dry-run）
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 --dry-run

# 対象 stem を絞る場合
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --illustration-stem illustration_01 --dry-run

# formatter を明示して比較する場合
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --illustration-stem illustration_01 \
  --prompt-formatter natural_sections --dry-run

# 本番実行（「OK」を確認してから）
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --illustration-stem illustration_01
```

---

### L-2. 表紙合成・題字ロゴ（Cover Composition）

```text
題字ロゴを計画してください。
```

または:

```text
表紙合成して proof を出してください。
```

**このように動きます:**
1. `_meta.md` §3.1 の題字方針（`組版` / `logo_asset`）を確認する
2. `logo_asset` なら `cover/title_logo_plan.md` を起こし、dry-run → 承認 → 採用PNG → `cover.yaml` を差し替える
3. `組版` なら `cover.yaml` の title を `type: text` で整える
4. `book_cover_review.py` で確認し、`_meta.md` §3.1／§7 を更新する

詳細は [表紙合成・題字ロゴ](cover-composition.md)。

---

### L-3. 出版パッケージと proof PDF

```text
出版パッケージを点検して lock してください。
```

```text
bunko の reader-proof を出してください。
```

**このように動きます:**
1. `book_review.py --gate export` → `book_lock.py` → `book_diff.py`
2. `book_export.py --profile bunko|jis_b5` で interior / reader-proof を生成する
3. `book_preflight.py` で errors=0 を確認し、`_meta.md` §7 を同期する

詳細は [Publishing Package](publishing-package.md) と [紙書籍 proof PDF](paper-proof-export.md)。

---

### M. 背景画像（背景資料）を生成する

コマ絵・ページ絵を描く前に、場所・光源・構図・物品配置を固めるための背景資料画像を出します。人物を主役にせず、空間設計を先に作ることで、後続のコマ生成やページ生成の参照素材になります。

```text
漫画ページの背景資料を生成してください。
```

**このように動きます:**
1. `manga/pages/*.yaml` の `background_concepts[]` フィールドを読む
2. `.env` の `MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT`（既定: `grok`）を確認する
3. `--dry-run` でプロバイダ名・ジョブ数・保存先をチャットに提示する
4. ユーザーの「OK」を受けてから本番実行する（承認なしには実行しない）
5. `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` に保存されたことを確認して報告する

生成後は採用した構図・光・小道具を `manga/pages/*.yaml` の `scene` や `render_instruction` に書き戻して、コマ生成・ページ生成に活かします。

**使われるツール:**

```bash
# 背景資料生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source background-concepts --dry-run

# 背景資料生成（本番）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source background-concepts
```

> この操作は [ワークフロー詳細仕様](../../.rulesync/rules/workflow-specification.md) の「生成モード用語」および `docs/image-generation/index.md`「背景資料生成」節に定義があります。

---

---

### A'. チャットモードで始める（対話型執筆 / TRPG）

```text
チャットモードで新規作品を始めたいです。
```

**このように動きます:**
1. Phase 0（作品契約）として読後感・主軸・トーン・尺感・結末の方向・禁止事項の6項目を確認する
2. 合意した内容を `proposal.md` または `_meta.md` の「作品契約」節に保存する
3. Phase 1〜2（あらすじ・執筆前パック）へ進み、軽量な資料を揃える
4. Phase 3〜4（シーンカード → セグメント執筆 → ゲート）を繰り返す

TRPG セッション形式にしたい場合:

```text
TRPGセッション形式で進めたいです。
```

**このように動きます（TRPG）:**
1. `proposal.md` / `world.md` / `character.md` を読んでジャンルを判断する
2. ジャンルに合ったパラメータを選び、`_chat/rulebook.md` を作成してユーザーに確認を求める
3. 承認後に `_chat/state/char_state.md` / `world_state.md` を初期化する
4. GM として物語を語り、イベントごとに `[STATE UPDATE]` ブロックでパラメータを更新する
5. セッション終了後、ログを清書して `_novel_text/` に保存する

詳細は [チャットモード](chat-writing-mode.md) を参照してください。

---

## その他のツール

手動で実行できる全ツールの一覧とコマンド例は [Tools（ツールリファレンス）](../tools/index.md) を参照してください。

---

## 出力の確認ポイント

Monogatari Coach は、チャット欄への書き込みだけでは作業を完了しません。以下のファイルに実際に保存されている状態が正本です。

| 操作 | 保存先 |
|------|--------|
| 小説本文 | `novels/<作品>/_novel_text/novel_text*.md` |
| 清書稿（書き直し後） | 同上（旧版は `_novel_text_backup/` へ退避） |
| 書評（下読み） | `novels/<作品>/_reader/YYYYMMDD_HHMM.md` |
| 興味判定 | `novels/<作品>/_reader/interest_YYYYMMDD.md` |
| キャラタグ（正本） | `novels/<作品>/tag/characters/<id>.yaml` |
| キャラタグ（互換） | `novels/<作品>/tag/<romaji>.md` |
| 漫画ページ（正本） | `novels/<作品>/manga/pages/manga_XX_pYY.yaml` |
| 漫画ページ（互換） | `novels/<作品>/manga/manga_XX.md`（**`novel_prompt_ir_export_md.py` で生成**。手書き・チャットのみは正本扱いにしない） |
| 挿絵・表紙（正本） | `novels/<作品>/illustrations/pages/illustration_XX_pYY.yaml` |
| 生成画像（キャラ） | `novels/<作品>/tag/<romaji>/` |
| 生成画像（漫画） | `novels/<作品>/manga/_assets/<manga_XX>/comic/` |
| 背景資料画像 | `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` |
| 生成画像（挿絵・表紙） | `novels/<作品>/illustrations/_assets/<illustration_XX>/` |

文字数は `tools/novel_char_count.py` の集計結果を根拠にします。エディタ上の文字数や目視での推定は使いません。
