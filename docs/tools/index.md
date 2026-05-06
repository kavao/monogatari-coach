# ツールリファレンス

`tools/` 配下のスクリプトとシステム管理コマンドの一覧です。Monogatari Coach が内部で自動呼び出しするものと、ユーザーが手動でも実行できるものの両方を掲載しています。

チャット指示とセットで動く操作フローは [指示出しベースのワークフロー](../workflow/instruction-driven.md) を参照してください。

---

## テキスト・プロジェクト管理

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
```

---

### `novel_code_allocate.py` — 作品番号採番

`novels/` 内の最大番号 +1 で `novel_code` を採番し、`config.md` との整合を検証します。

```bash
python tools/novel_code_allocate.py novels/
```

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
```

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
- コマ・ページ: `novels/<作品>/manga/_assets/<manga_XX>/`
- 背景資料: `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/`

---

## レイアウト・フォルダ管理

### `novel_image_layout.py` — 画像フォルダの一括作成

キャラクター画像・漫画コマ画像の保存フォルダを一括で作成します。

```bash
# 作品フォルダ内の画像フォルダを一括作成
python tools/novel_image_layout.py scaffold novels/NNN_作品名

# コマ用スロットフォルダを指定枚数作成（任意）
python tools/novel_image_layout.py scaffold novels/NNN_作品名 --panels 4
```

---

## ログ・記録

### `workspace_audit_log.py` — 査証ログ・日記の追記

`_workingspace/log/(YYYYMM).md` にセッションの作業記録を追記します。既存行の上書き・削除は行いません。

```bash
# 査証ログに追記
python tools/workspace_audit_log.py append "作業内容の説明"

# 日記（横断ナレッジ）に追記
python tools/workspace_audit_log.py diary append "学びや判断の記録"

# 当月ファイルのパスを確認
python tools/workspace_audit_log.py path

# 整合性の検証
python tools/workspace_audit_log.py verify
```

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
rulesync generate
```

主編集先: `.rulesync/rules/*.md` / `.rulesync/skills/*/SKILL.md` / `.rulesync/mcp.json` / `.rulesync/hooks.json`

---

### `howto_init.py` — 初回セットアップ

`_how_to.example/` から `_how_to/` を、`.env.example` から `.env` を、未作成時にコピーします。

```bash
uv run python howto_init.py
```

---

### `tools_temp/` — ローカル試行領域

`tools/` の正規スクリプトを直接編集せず、コピーして試行錯誤するための一時領域です。Git 管理外（`README.md` のみ追跡）。

```bash
# 例: 正規スクリプトをコピーしてから編集
cp tools/novel_prompt_ir_export_md.py tools_temp/my_test.py
```

詳細は [`/tools_temp/README.md`](../../tools_temp/README.md) を参照。
