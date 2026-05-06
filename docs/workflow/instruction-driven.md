# 指示出しベースのワークフロー（ユーザー視点）

このページを読むと、Monogatari Coach にチャットで何をどう指示すれば制作が進むかがわかります。

各指示は**一言で動くように内部でルール化**されています。長いテンプレートは「より詳しく指定したいとき」の補足です。

各操作の「**使われるツール**」欄は、Monogatari Coach が内部で呼び出す CLI コマンドです。手動でも実行できます（`※ 自動呼び出し` と書いたものも含む）。

詳細な仕様（`.rulesync/`）を読まなくても、まずはこのページの導線で動かせることを目的にしています。

---

## 初回導入

### 1. 状態確認

```text
初回導入の設定をしてください。
```

**このように動きます:**
1. リポジトリの初期化状態（`.env`・`rulesync` 生成物の有無）を確認する
2. 不足があれば「次に実行するコマンド」「`.env` に埋めるべきキー」を一覧で提示する
3. 問題がなければそのまま制作の目的確認へ進む

**使われるツール:**

```bash
# 初回セットアップ（_how_to/ と .env を未作成時にコピー）
uv run python howto_init.py

# ルール・スキルの生成物を同期
rulesync generate
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

### D. 下読み（足きり判定）する

```text
第1章を下読みして書評を出してください。
```

**このように動きます:**
1. `_how_to/reader.md` の評価観点（キャラ・プロット・文章力・独創性など）を参照する
2. 商業的な最低基準をクリアしているかを編集者の視点で判定する
3. 結果を `novels/<作品>/_reader/YYYYMMDD_HHMM.md` に保存する
4. チャットには判定（合格／不合格・5段階評価）と改善ポイントの要約だけを返す

*（このモードは LLM が直接処理するため、CLI ツールは使いません）*

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

画像タグや漫画ページは、本文が進んだ段階で別モードとして動かせます。

### G. キャラクター画像タグを作る（Tag Mode）

```text
プロフィールからタグを作成してください。
```

**このように動きます:**
1. `character.md` を読んで外見・服装・固定特徴を把握する
2. `tag/characters/<character_id>.yaml` に YAML IR（構造化タグ定義）を作成する
3. `tag/<romaji>.md` に互換 Markdown を出力する（画像生成バッチで使用）

**使われるツール:**

```bash
# 画像保存先フォルダを一括作成 ※ 自動呼び出し
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# YAML IR → 互換 Markdown へエクスポート ※ 自動呼び出し
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --output-dir novels/NNN_作品名
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
4. `novels/<作品>/manga/_assets/<manga_XX>/` に画像が保存されたことを確認して報告する

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

# ページ生成（本番）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait
```

---

### K. 背景画像（背景資料）を生成する

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

> この操作は `.rulesync/rules/overview.md` §2.2.2「生成モードの用語統一」および `docs/image-generation/index.md`「背景資料生成」節に定義があります。

---

## その他のツール（間接的に使われるもの）

Monogatari Coach が内部で利用するツールのうち、ユーザーが直接呼び出すことは少ないものをまとめます。知っておくと手動で実行・確認したいときに役立ちます。

| ツール | 用途 | CLI 例 |
|--------|------|--------|
| `tools/workspace_audit_log.py` | 査証ログ・日記への追記 | `python tools/workspace_audit_log.py append "内容"` |
| `tools/novel_code_allocate.py` | 作品番号（novel_code）の採番・検証 | `python tools/novel_code_allocate.py novels/` |
| `tools/novel_project_check.py` | 必須ファイル・ディレクトリの揃いを確認 | `python tools/novel_project_check.py novels/NNN_作品名` |
| `tools/novel_char_count.py` | 小説本文の文字数を集計 | `python tools/novel_char_count.py novels/NNN_作品名` |
| `tools/novel_image_layout.py` | 画像保存先フォルダを一括作成 | `python tools/novel_image_layout.py scaffold novels/NNN_作品名` |
| `tools/novel_prompt_ir_embed_snapshots.py` | キャラ外見をページ YAML に埋め込む | `python tools/novel_prompt_ir_embed_snapshots.py novels/NNN_作品名` |
| `tools/novel_prompt_ir_validate.py` | YAML IR の型・参照・品質を検証 | `python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality` |
| `tools/novel_prompt_ir_export_md.py` | YAML IR を互換 Markdown に変換 | `python tools/novel_prompt_ir_export_md.py --help` |
| `tools/image_provider_generate.py` | 単体画像を1枚生成（バッチではなく手動試作向け） | `python tools/image_provider_generate.py --probe --provider forge` |
| `tools/json_weighted_pick.py` | JSON リストから確率付き乱数選択（命名などで使用） | `python tools/json_weighted_pick.py _how_to/name_creature.json` |
| `tools/codex_builtin_image_archive.py` | Codex 内蔵画像を作品フォルダへアーカイブ | `python tools/codex_builtin_image_archive.py --help` |

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
| 漫画ページ（互換） | `novels/<作品>/manga/manga_XX.md` |
| 生成画像（キャラ） | `novels/<作品>/tag/<romaji>/` |
| 生成画像（漫画） | `novels/<作品>/manga/_assets/<manga_XX>/` |
| 背景資料画像 | `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` |

文字数は `tools/novel_char_count.py` の集計結果を根拠にします。エディタ上の文字数や目視での推定は使いません。
