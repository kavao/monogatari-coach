# ツールリファレンス

`tools/` 配下のスクリプトとシステム管理コマンドの一覧です。Monogatari Coach が内部で自動呼び出しするものと、ユーザーが手動でも実行できるものの両方を掲載しています。

チャット指示とセットで動く操作フローは [指示出しベースのワークフロー](../workflow/instruction-driven.md) を参照してください。

---

## テキスト・プロジェクト管理

### `novel_onboard.py` — 新規作品オンボーディング

新規作品を1コマンドで準備します。作品名を渡すと採番・フォルダ作成・scaffold・プロジェクト確認・次の一言まで一括で実行します。

```bash
# 作品名を渡す（コードを自動採番）
python tools/novel_onboard.py "作品タイトル"

# フルパスを指定（コードはパスから取得）
python tools/novel_onboard.py novels/067_作品タイトル

# 実行前に採番とフォルダパスだけ確認する
python tools/novel_onboard.py "作品タイトル" --dry-run
```

実行後は `[Plan Mode]` または `[チャットモード開始]` の案内に従って制作を始めます。

---

### `novel_status.py` — 作品ダッシュボード

作品フォルダの状態を1コマンドで一覧表示します。プロジェクト状態・本文文字数・漫画 IR 件数・最新生成画像・`_meta.yaml` 設定を一画面に集約します。セッション再開時や「今どこまで進んでいるか」を確認したいときに使います。

```bash
# 作品の状態を確認する
python tools/novel_status.py novels/NNN_作品名

# 漫画 IR の検証も同時に行う
python tools/novel_status.py novels/NNN_作品名 --validate

# 次にすべきことだけを1行で確認する（状態機械による判定）
python tools/novel_status.py novels/NNN_作品名 --next
```

`--next` は「ファイルが何も揃っていない→Plan Mode」「本文はあるがタグがない→Tag Mode」など、ファイルシステムの状態から次のステップを自動判定します。チャットモード作品（`_meta.md` に「執筆モード: チャットモード」がある）は「次のセグメントを執筆してください」を返します。

詰まったときは [トラブルシューティング](../workflow/troubleshooting.md) を参照してください。

---

### `novel_char_count.py` — 文字数集計

小説本文（`_novel_text/*.md`）の文字数を Unicode NFC コードポイントで集計します。エディタの文字数カウントではなく、このスクリプトの結果を公式数値として扱います。

```bash
# 作品フォルダ全体（章別 + 合計）
python tools/novel_char_count.py novels/NNN_作品名

# 特定ファイルのみ
python tools/novel_char_count.py novels/NNN_作品名/_novel_text/novel_text01.md
```

---

### `novel_project_check.py` — 必須ファイル確認

執筆開始前に、作品フォルダの必須ファイル・ディレクトリが揃っているかを確認します。終了コード 0 で「問題なし」です。

```bash
# 基本確認
python tools/novel_project_check.py novels/NNN_作品名

# Tag Mode 済みを必須にする場合
python tools/novel_project_check.py novels/NNN_作品名 --require-tag

# 漫画フォルダまで揃えたい場合
python tools/novel_project_check.py novels/NNN_作品名 --require-manga-dir

# G3 足切り通過を必須にする場合（_meta.md または最新 _reader/*.md を確認）
python tools/novel_project_check.py novels/NNN_作品名 --require-slush-g3

# _meta.yaml 等を不足分だけ作成してからチェック
python tools/novel_project_check.py novels/NNN_作品名 --bootstrap
```

`--require-slush-g3` は、`_meta.md` に「足切りステータス: G3合格」が記録されているか、または最新の `_reader/YYYYMMDD_HHMM.md` に「スコア ≥ 55 かつ読むべき」が記録されているかを確認します。投稿前のゲートや校正着手前の確認に使います。

---

### `novel_character_md_check.py` — character.md 構造 lint

`character.md` の見出し・必須フィールド・表形式を、`_how_to` のチェックリスト YAML（既定: `_how_to.example/character_checklist.yaml`）に基づいて検証します。Tag Mode 前の Plan 段階で書き漏れを検出する用途です（外見の機械正本は `tag/characters/*.yaml`）。

```bash
# 作品フォルダ全体の character.md を検証
python tools/novel_character_md_check.py novels/NNN_作品名

# 厳格モード（移行猶予の WARN も ERROR）
python tools/novel_character_md_check.py novels/NNN_作品名 --strict

# 不足項目の追記案を表示
python tools/novel_character_md_check.py novels/NNN_作品名 --suggest
```

---

### `novel_scaffold.py` — 新規作品の `_meta.yaml` 雛形

Plan Mode で作品フォルダを作った直後に実行します。`_meta.yaml`（雛形: `_how_to.example/_meta.yaml.example`）、`references/novelai/README.md`、`_novel_text/`、`_reader/` を作成します。既存の `_meta.yml` は `_meta.yaml` にリネームします。

```bash
python tools/novel_scaffold.py novels/NNN_作品名

# _meta.yaml のみ
python tools/novel_scaffold.py novels/NNN_作品名 --meta-only
```

---

### `novel_code_allocate.py` — 作品番号採番

`novels/` 内の最大番号 +1 で `novel_code` を採番し、`config.md` との整合を検証します。

```bash
python tools/novel_code_allocate.py novels/
```

---

### `novel_text_rewrite_lint.py` — 本文 rewrite 機械 lint

`_novel_text/*.md` を `rewrite.md`（§1・§9）の体裁規則に基づいて検査し、行番号付きで問題を報告します。清書後の取りこぼし確認と、清書完了ゲートに使います。

ルール定義は `_how_to.example/novel_text_rewrite_rules.yaml`（作品単位の上書きは `novels/<作品>/novel_text_rewrite_rules.yaml`）で管理します。

**検出するルール（既定プロファイル `default`）**:

プロファイルによって検出内容を切り替えます。

| `--profile` | 対象ルール | 主な用途 |
|-------------|-----------|---------|
| `default`（既定） | 章メタ・三点リーダー・`。」` | 清書後の取りこぼし確認 |
| `grammar` | セリフ行頭・段落インデント・句読点連続・半角カンマ・空括弧・助詞重複・全角スペース | **執筆直後**のクイックチェック／`--fix` |
| `full` | `default` + `grammar` の全ルール | 清書前の総合チェック |
| `minimal` | 三点リーダー・`。」` のみ | 旧稿を句読点から直したいとき |

**検出ルール一覧**:

| rule_id | 内容 | レベル | profile |
|---------|------|--------|---------|
| `chapter_meta_label` | 「第○章」「前章」「次章」などの章番号・ラベル | warning | default/full |
| `chapter_meta_compare` | 「第○章と同じ」等の前章比較 | warning | default/full |
| `author_meta` | 「この章では」「プロットどおり」等の執筆者目線 | warning | default/full |
| `ellipsis_ascii` | 半角 ASCII `...` の連続 | **error** | default/full |
| `ellipsis_wrong_unicode` | 単独「…」（U+2026 × 1） | warning | default/full |
| `dialogue_trailing_period` | 閉じカギ括弧直前の句点（`。」`） | warning | default/full |
| `dialogue_leading_indent` | セリフ行頭の全角スペース（`　「`） | warning | grammar/full |
| `paragraph_indent` | 地の文の行頭インデント不足 | warning | grammar/full |
| `punctuation_consecutive` | `。。` `、、` など句読点の連続 | **error** | grammar/full |
| `ascii_comma_in_prose` | 英数字以外の直後の半角 `,`（`うん,そう` 等） | warning | grammar/full |
| `empty_dialogue` | 空のカギ括弧 `「」` | warning | grammar/full |
| `duplicate_particle` | `をを` `がが` など助詞の重複 | info | grammar/full |
| `fullwidth_space_double` | 全角スペースの連続 `　　` | info | grammar/full |

**推奨ワークフロー（全体）**:

| 段階 | コマンド | 意味 |
|------|----------|------|
| 執筆直後 | `grammar --fix-dry-run` → `grammar --fix` → `grammar` | 誤打の機械校正（**清書の代わりではない**） |
| 清書前 | `--profile full` | A〜E の総合チェック |
| 清書後 | `--strict`（既定 `default`） | 清書完了ゲート |

```bash
# 0. 執筆直後 — 誤打・体裁を機械校正（profile grammar 必須）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md --profile grammar --fix-dry-run
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md --profile grammar --fix
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md --profile grammar

# 1. 清書前 — rewrite ルールと文法を総合チェックする
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --profile full

# 2. rewrite.md に従って清書（_novel_text_backup/ に退避してから _novel_text/ を更新）

# 3. 清書完了ゲート — warning も exit 1 にして残りがないことを確認する
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --strict
```

`--fix` で自動置換できる rule_id: `dialogue_leading_indent` `ascii_comma_in_prose` `ellipsis_ascii` `dialogue_trailing_period` `paragraph_indent`（いずれも **grammar プロファイル有効時**）。句読点連続・空「」・助詞重複は検出のみ。

```bash
# 単一ファイルを確認する
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md

# CI・エージェント向けに JSON で出力する
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --json

# 設定ファイルパスと有効ルールを表示する
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --verbose
```

スキル: 執筆直後は **`novel-text-file-output`** → **`novel-text-rewrite-lint`**（`grammar --fix`）。清書は **`novel-refinement-output`**。

清書が完了したら `--strict` で exit 0 を確認してから「清書完了」と報告します（`novel-refinement-output` スキルと連動）。

物語内カウンタ（「二回目の◎」など）を誤検知する場合は、`novels/<作品>/novel_text_rewrite_rules.yaml` の `allowlist_patterns` に追加します。

#### novel-refinement-output との連携（推奨手順）

`novel-refinement-output` スキルの手順6（確認）のあとに lint を実行するのが推奨ワークフローです。

```bash
# ① 清書前: 全体チェック（A〜E 全ルール）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --profile full

# ② rewrite.md に従って清書する（旧版を _novel_text_backup/ に退避してから更新）

# ③ 清書後ゲート: --strict で warning も 0 を確認してから完了報告する
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --strict
```

ステップ③で exit 0 が出たら、`_meta.md` の進捗節に以下の形式でメモを残します。

```
- lint: --strict で exit 0 確認（YYYY-MM-DD、profile: full → strict）
```

この1行が「清書完了」の機械的根拠として機能します。査証ログ（`_workingspace/log/YYYYMM.md`）にも同内容を追記してください。

---

---

## 評価・下読み

下読み・Editor Score・一貫性監査の前後に使うツール群です。チャットで評価を依頼するときの準備と結果確認をサポートします。

詳しい評価フローは [Reader Output](../workflow/reader-output.md) を参照してください。

### `novel_evaluation_prepare.py` — 評価セッション準備

評価を始める前に、章別文字数・既存評価ファイルの一覧・frontmatter テンプレートを表示します。

```bash
# First Reader 用の準備情報を表示する（既定: --mode first-reader --gate G3）
python tools/novel_evaluation_prepare.py novels/NNN_作品名

# G2 足切り用
python tools/novel_evaluation_prepare.py novels/NNN_作品名 --gate G2

# Editor Score 用（あらすじ・スコア参照先を含む frontmatter テンプレを表示）
python tools/novel_evaluation_prepare.py novels/NNN_作品名 --mode editor-score
```

章グループ（`ch01`〜`chNN`）ごとの文字数と合計・プロローグの別途カウント・`_reader/` に存在する評価ファイルとスコアを一覧表示します。コピー用の frontmatter テンプレートも出力します。

---

### `novel_evaluation_diff.py` — 評価スコア推移

`_reader/` 内の評価ファイルを時系列で並べ、スコアの変化を表示します。清書前後の点差確認や、複数回の G1→G2→G3 評価の推移を追うときに使います。

```bash
# スコアが付いたファイルのみ表示（First Reader・Editor Score）
python tools/novel_evaluation_diff.py novels/NNN_作品名

# Synopsis・Interest Check も含めて全ファイルを表示
python tools/novel_evaluation_diff.py novels/NNN_作品名 --all
```

フロントマターをスキップして本文スコアを正確に抽出します。旧形式（5段階・`4.5 / 5.0`）のファイルは「旧形式」として識別します。

---

### `novel_slush_gate_lint.py` — 評価ファイル必須項目チェック

First Reader 評価ファイル（`_reader/YYYYMMDD_HHMM.md`）に必須の12項目（判定・総合点/100・ゲート段階・6評価項目・判定理由・足切り理由・改善点）が揃っているかを機械確認します。

```bash
# 特定ファイルをチェックする
python tools/novel_slush_gate_lint.py novels/NNN_作品名/_reader/YYYYMMDD_HHMM.md

# 作品フォルダを指定すると最新 YYYYMMDD_HHMM.md を自動選択する
python tools/novel_slush_gate_lint.py novels/NNN_作品名

# WARN も ERROR 扱いにする（厳格モード）
python tools/novel_slush_gate_lint.py novels/NNN_作品名 --strict

# JSON で出力する（CI 向け）
python tools/novel_slush_gate_lint.py novels/NNN_作品名 --json
```

終了コード: 0（全通過）/ 1（ERROR あり）/ 2（WARN あり）/ 3（ファイルなし）

旧形式ファイル（`reader_YYYYMMDD_HHMM.md`）には `総合点/100` 項目が存在しないため、ERROR になります。旧形式の評価は参考記録として残し、新形式で再評価することを推奨します。

---

## IR（中間表現）関連

漫画ページ・キャラクタータグを YAML IR（構造化定義ファイル）として管理するためのツール群です。IR の概要は [manga-prompt-ir.md](../image-generation/manga-prompt-ir.md) を参照してください。

### `novel_prompt_ir_validate.py` — YAML IR 検証

`manga/pages/*.yaml` および `tag/characters/*.yaml` の型・参照・品質を検証します。本番生成前に必ず実行します。

```bash
# 型・参照の基本検証
python tools/novel_prompt_ir_validate.py novels/NNN_作品名

# 品質警告も失敗扱いにする（本番前推奨）
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality
```

---

### `novel_prompt_ir_embed_snapshots.py` — スナップショット埋め込み

`tag/characters/*.yaml` のキャラクター外見情報を、各ページ YAML の `character_snapshots[]` に埋め込みます。ページ YAML 単体で外見が確定した状態になります。

```bash
python tools/novel_prompt_ir_embed_snapshots.py novels/NNN_作品名
```

---

### `novel_prompt_ir_export_md.py` — YAML IR → 互換 Markdown エクスポート

YAML IR から `tag/<romaji>.md`（キャラタグ）または `manga/manga_XX.md`（漫画ページ）の互換 Markdown を出力します。バッチ生成ツールや手作業でのタグ確認に使います。

```bash
# キャラクタータグの Markdown 出力
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --output-dir novels/NNN_作品名

# 漫画ページの Markdown 出力（NovelAI パイプタグ付き）
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml \
  --output-dir novels/NNN_作品名 --manga-stem manga_01 --novelai-pipe-tags

# ヘルプを見る
python tools/novel_prompt_ir_export_md.py --help
```

---

### `novel_prompt_ir_migrate_character_tags.py` — レガシー `character_tags` の移行

旧形式のルート `character_tags` を `000_base.danbooru_tags` へ移し、レガシーキーを削除します。YAML IR 刷新時の一括移行向けです。

```bash
# 1作品を dry-run で確認
python tools/novel_prompt_ir_migrate_character_tags.py novels/NNN_作品名 --dry-run

# 本番移行
python tools/novel_prompt_ir_migrate_character_tags.py novels/NNN_作品名

# novels/ 配下を一括（露出タグ検出時は --strict で停止）
python tools/novel_prompt_ir_migrate_character_tags.py --all-novels --dry-run
```

---

### `novel_manga_panel_summary_en.py` — コマ要約の英訳（`summary_en`・任意）

`manga/pages/*.yaml` の `panels[].summary` を Chat API で英訳し、`summary_en` / `summary_en_source` を書き込みます。**Manga Tag Mode の主経路はエージェント同時翻訳＋`novel_prompt_ir_validate.py --strict-quality`**（`concepts.md`「Manga `summary_en` の翻訳経路」）。本ツールはエージェントなし編集・一括再翻訳向けの**任意**経路です。provider は `.env` の `MONOCRI_SUMMARY_EN_*` を参照します。

```bash
# 作品フォルダ内の全ページを処理（要 API キー）
python tools/novel_manga_panel_summary_en.py novels/NNN_作品名

# 単一ページのみ（dry-run で対象確認）
python tools/novel_manga_panel_summary_en.py novels/NNN_作品名 \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml --dry-run

# 主経路の完了確認（翻訳ツールの有無に関わらず推奨）
python tools/novel_prompt_ir_validate.py novels/NNN_作品名 --strict-quality
```

---

### `novel_meta_yaml.py` — `_meta.yaml` 読み込み（内部モジュール）

作品 `_meta.yaml` の読み込み・`novelai.portions` 解決・`character_tag_batch` 参照を提供する Python モジュールです。**単独の公開 CLI ではありません。** `image_provider_novel_*_batch.py`・`novel_status.py` などから import されます。雛形は `_how_to.example/_meta.yaml.example`、運用説明は [Image Generation — 名前付きレシピ](../image-generation/index.md#名前付きレシピworkflows) を参照してください。

---

### `novel_manga_apply_tag_defaults.py` — §5 漫画タグ層の自動転記

`_meta.md` の §5「漫画タグ層（区間・常時上乗せ）」テーブルを読み取り、対応するページ YAML（`manga/pages/*.yaml`）の `render_instruction.user_directives.defaults` へ転記します。§5 を手動でページ YAML に書き写す作業を省き、書き忘れ・書き間違いを防ぎます。

**固定手順（MD 表を編集 → YAML 反映 → 画像生成へ）**:

```bash
# 1. _meta.md §5 テーブルを編集したあと、転記内容を確認する（dry-run・既定）
python tools/novel_manga_apply_tag_defaults.py novels/NNN_作品名

# 2. 問題なければ実際にページ YAML へ書き込む
python tools/novel_manga_apply_tag_defaults.py novels/NNN_作品名 --apply

# 3. IR を検証する（本番生成前推奨）
python tools/novel_prompt_ir_validate.py novels/NNN_作品名

# 4. 必要なら互換 Markdown を再エクスポートして画像生成 dry-run へ進む
python tools/novel_prompt_ir_export_md.py \
  --character novels/NNN_作品名/tag/characters/chara.yaml \
  --manga-page novels/NNN_作品名/manga/pages/manga_01_p01.yaml \
  --output-dir novels/NNN_作品名 --manga-stem manga_01 --novelai-pipe-tags
```

`--apply` で書き換わる場所:
- `manga/pages/<ページ>.yaml` の `render_instruction.user_directives.defaults.required_prompt_tags`
- `manga/pages/<ページ>.yaml` の `render_instruction.user_directives.defaults.omit_prompt_tags`
- 追跡用の `page_notes` エントリ（`--no-note` で省略可）

**§5 テーブルの書き方（`_meta.md` 内）**:

| 区間 | 本文参照 | required | omit | メモ |
|------|---------|----------|------|------|
| manga_01_p01 | novel_text01 浴室 | steam, bathroom, bathtub | outdoor, sky | — |
| manga_01_p02–p04 | 同シーン継続 | steam, bathtub, upright_straddle | outdoor, sky | |

区間には単一ページ（`manga_01_p01`）と範囲指定（`manga_01_p01–p04`、em dash / en dash / ハイフンのいずれも可）が使えます。

```bash
# _meta.md のパスを直接指定する場合
python tools/novel_manga_apply_tag_defaults.py novels/NNN_作品名 \
  --meta path/to/_meta.md --apply

# page_notes への追記を省略する場合
python tools/novel_manga_apply_tag_defaults.py novels/NNN_作品名 --apply --no-note
```

---

## 画像生成関連

画像生成の設定・プロバイダ選択・dry-run の詳細は [Image Generation](../image-generation/index.md) を参照してください。

### `image_provider_generate.py` — 単体画像生成

バッチではなく1枚だけ手動で試作するときや、プロバイダの疎通確認に使います。

```bash
# Forge の疎通確認
python tools/image_provider_generate.py --probe --provider forge

# params ファイルを使った dry-run
python tools/image_provider_generate.py \
  --params tools/fixtures/grok_params.tier_test.example.json --dry-run
```

---

### `image_provider_novel_tag_batch.py` — キャラタグ一括生成

`tag/<romaji>.md` を参照してキャラクター画像を一括生成します。

```bash
# 確認（dry-run）
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名 --dry-run

# 本番実行
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名

# provider を明示する場合
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名 --provider novelai

# 全ジョブの positive 先頭へタグを追加（試行・一時運用向け）
python tools/image_provider_novel_tag_batch.py novels/NNN_作品名 \
  --prepend-tags solo simple_background --dry-run
```

**プロンプトのタグ順**（positive）: 品質プリフィックス → `prepend_tags` → 固定タグ（YAML）→ バリアント `danbooru_tags` → `append_tags`。

| 指定場所 | キー / フラグ |
|----------|----------------|
| 作品 `_meta.yaml` | `character_tag_batch.prepend_tags` / `append_tags` など |
| `tag/characters/<id>.yaml` | `tag_batch.prepend_tags` など（任意） |
| CLI（その実行のみ） | `--prepend-tags` / `--append-tags` / `--prepend-negative-tags` / `--append-negative-tags` |

生成画像の保存先: `novels/<作品>/tag/<romaji>/`

---

### `image_provider_novel_manga_batch.py` — 漫画ページ・コマ一括生成

`manga/pages/*.yaml`（または互換 Markdown）を参照して漫画画像を一括生成します。

```bash
# コマ生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels --dry-run

# コマ生成（本番）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels

# 精密ページ生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-pages \
  --aspect-ratio manga_b5_portrait --dry-run

# ページ生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step2-pages \
  --aspect-ratio manga_b5_portrait --dry-run

# 背景資料生成（dry-run）
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source background-concepts --dry-run
```

生成モードの詳細は [Image Generation](../image-generation/index.md) の「生成モードとプロバイダの対応」テーブルを参照。

生成画像の保存先:
- コマ・ページ: `novels/<作品>/manga/_assets/<manga_XX>/comic/`
- 背景資料: `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/`

---

### `image_provider_novel_illustration_batch.py` — 挿絵・表紙一括生成

`illustrations/pages/*.yaml` を参照して、挿絵・章扉・表紙画像を一括生成します。まず dry-run でプロンプト、provider、保存先を確認します。

```bash
# 挿絵・表紙生成（dry-run）
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 --dry-run

# 対象 stem を絞る場合
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --illustration-stem illustration_01 --dry-run

# prompt formatter を明示する場合
python tools/image_provider_novel_illustration_batch.py novels/NNN_作品名 \
  --illustration-stem illustration_01 \
  --prompt-formatter natural_sections --dry-run
```

生成画像の保存先: `novels/<作品>/illustrations/_assets/<illustration_XX>/`

---

## レイアウト・フォルダ管理

### `novel_image_layout.py` — 画像フォルダの一括作成

キャラクター画像・漫画コマ画像・背景資料・挿絵/表紙の保存フォルダを一括で作成します。

```bash
# 作品フォルダ内の画像フォルダを一括作成
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# コマ用スロットフォルダを指定枚数作成（任意）
python tools/novel_image_layout.py scaffold novels/NNN_作品名 --panels 4
```

---

## ログ・記録

### `workspace_audit_log.py` — 査証ログ・日記の追記

`_workingspace/log/(YYYYMM).md` にセッションの作業記録を、`_workingspace/diary/(YYYYMM).md` に横断ナレッジを追記します。既存行の上書き・削除は行いません。

```bash
# 査証ログに追記
python tools/workspace_audit_log.py append "作業内容の説明"

# 日記（横断ナレッジ）に追記
python tools/workspace_audit_log.py diary append "学びや判断の記録"

# 当月ファイルのパスを確認
python tools/workspace_audit_log.py path
python tools/workspace_audit_log.py diary path

# 整合性の検証
python tools/workspace_audit_log.py verify
python tools/workspace_audit_log.py diary verify
```

査証ログは「何をしたか」の事実、日記は「なぜそうするか・次回以降も使う判断理由」を残す場所です。

---

## ユーティリティ

### `json_weighted_pick.py` — 確率付き乱数選択

JSON リストから均等または確率フィールドに基づいて要素を選びます。キャラクター命名（`_how_to/name_creature.json`）などで使います。

```bash
python tools/json_weighted_pick.py _how_to/name_creature.json
```

---

### `codex_builtin_image_archive.py` — Codex 内蔵画像のアーカイブ

Codex の会話内蔵 `image_gen` で生成した画像（`C:\Users\Owner\.codex\generated_images\...`）を作品フォルダへコピーします。

```bash
python tools/codex_builtin_image_archive.py --help
```

---

## システム管理

### `rulesync` — ルール・スキルの同期

`.rulesync/rules/` / `.rulesync/skills/` を編集したあと、各 AI ツールの設定フォルダ（`.codex/`、`.kilocode/` 等）へ生成物を同期します。

```bash
corepack pnpm dlx rulesync generate

# 後方互換ラッパーを使う場合
uv run python sync_rules.py
```

`corepack enable` は不要です。Windows では Node.js のインストール先に shim を作ろうとして権限エラーになることがあるため、Corepack から直接 `pnpm` を呼び出します。代替として `npm exec --yes rulesync -- generate` も使えます。

主編集先: `.rulesync/rules/*.md` / `.rulesync/skills/*/SKILL.md` / `.rulesync/mcp.json` / `.rulesync/hooks.json`

---

### `howto_init.py` — 初回セットアップ

`_how_to.example/` から `_how_to/` を、`.env.example` から `.env` を、未作成時にコピーします。

```bash
uv run python howto_init.py
```

既に `_how_to/` や `.env` がある場合は上書きしません。`.env.example` がない場所で実行した場合、`.env` は作れません。

作業場所が正しいか確認するには、次を実行します。

```powershell
Get-Location
Test-Path .env.example
Test-Path .env
Get-ChildItem -Force .env*
git status --short
```

---

### `env_check.py` — `.env` 不足確認

`.env.example` の版、`.env` の不足キー、選択中 provider に必要な API キー不足を確認します。

```bash
python tools/env_check.py
```

---

### `tools_temp/` — ローカル試行領域

`tools/` の正規スクリプトを直接編集せず、コピーして試行錯誤するための一時領域です。Git 管理外（`README.md` のみ追跡）。

```bash
# 例: 正規スクリプトをコピーしてから編集
cp tools/novel_prompt_ir_export_md.py tools_temp/my_test.py
```

詳細は [`/tools_temp/README.md`](../../tools_temp/README.md) を参照。
