---
name: novel-image-layout
description: >-
  作品フォルダ内で tag/<romaji>/（キャラ画像）、manga/_assets/<manga_XX>/（漫画・コマ画像）、
  illustrations/_assets/<illustration_XX>/（挿絵・表紙画像）のディレクトリを
  tools/novel_image_layout.py で一括作成・パス列挙する。
  Forge txt2img の output_dir と組み合わせる。
targets: ["*"]
---

## 目的

`.rulesync/rules/concepts.md` の **「画像保存先」** と `overview.md` の Tag Mode / Manga Tag Mode 入口に合わせ、**フォルダだけ先に機械的に用意**する。

- **タグ**: `tag/kazuki.md` と同名の **`tag/kazuki/`** に、そのキャラの生成画像をすべて保存する。
- **漫画**: `manga/manga_01.md` に対応する **`manga/_assets/manga_01/`** に、そのページのコマ画像を保存する。**既定運用ではこの直下を使う。** ストックの分類は**章（`manga_XX`）まで**で足りる。
- **挿絵・表紙**: `illustrations/pages/illustration_01_p01.yaml` に対応する **`illustrations/_assets/illustration_01/`** に保存する。`_pNN` はページ番号なので、保存先 stem からは外す。
- **`image_provider_novel_manga_batch --subdir-by-page` による `p01/`, `p02/` 等のページ単位サブフォルダ**は、本リポジトリの**推奨・ルールの対象外**（手順で既定にしない）。通常はファイル名接頭辞でページ・コマを区別する。
- **`k01`, `k02`, …** は、コマ別に手で整理したい場合だけ作る**任意**の補助フォルダ。通常運用では不要。

Markdown の中身の解析や画像のコピーは**行わない**（ディレクトリの scaffold / パス表示のみ）。

## 実行方法

リポジトリルート（`monocri/`）で、**作品フォルダ**を引数に取る。

**フォルダ作成**（`tag/*.md` があれば `tag/<stem>/`、`manga/manga_*.md` があれば `manga/_assets/<stem>/`、`illustrations/pages/illustration_XX_pYY.yaml` があれば `illustrations/_assets/illustration_XX/`）:

```bash
python tools/novel_image_layout.py scaffold novels/051_神のダンジョンβテスター
```

**任意でコマ用サブフォルダも同時作成**（各 `manga_XX` ごとに `k01` … `k12`。通常は不要）:

```bash
python tools/novel_image_layout.py scaffold novels/051_神のダンジョンβテスター --panels 12
```

**作成せず、推奨 `output_dir` だけ表示**（params JSON を書くときのコピー用。通常は直下パスだけ使う）:

```bash
python tools/novel_image_layout.py paths novels/051_神のダンジョンβテスター
python tools/novel_image_layout.py paths novels/051_神のダンジョンβテスター --panels 8
```

`-v` で scaffold 時に作成したパスを列挙。

## Forge との連携

- **`image_provider_generate`** の `output_dir` に、上記の **`tag/<romaji>`**、**`manga/_assets/<manga_XX>`**、または **`illustrations/_assets/<illustration_XX>`** を指定する。`k03` などは手動でコマ別に分けたい場合だけ使う。
- `file_prefix` には同一コマ内で重複しにくいよう **`manga_01_k03`** のように章ファイル名＋コマ番号を含めると追跡しやすい（スキル **`image-provider（旧 forge-txt2img）`** 参照）。
- **`tag/*.md` から Danbooru 行だけを読み、`tag/<romaji>/` にシーン別1枚ずつ**出す場合は `tools/image_provider_novel_tag_batch.py <作品フォルダ>`（`--dry-run` で抽出確認のみ）。
- **`manga/manga_*.md` の各コマ**（`## Page` → `## step1` 内の `tag:` … `和訳:`）を `manga/_assets/<manga_XX>/` に出す場合は `tools/image_provider_novel_manga_batch.py <作品フォルダ>`。**既定ではこの直下に保存され、`k01` などは使わない。** ファイル名接頭辞は `manga_01_p02_k03`（ページ・コマ番号）。
- **`illustrations/pages/*.yaml` の挿絵・表紙**を `illustrations/_assets/<illustration_XX>/` に出す場合は `tools/image_provider_novel_illustration_batch.py <作品フォルダ>`。まず `--dry-run` で保存先とプロンプトを確認する。

## 関連パス

- 規約: `.rulesync/rules/concepts.md`（画像保存先）
- 入口索引: `.rulesync/rules/overview.md`（Tag Mode / Manga Tag Mode）
- スクリプト: `tools/novel_image_layout.py`
- 画像生成: `tools/image_provider_generate.py`、スキル `.rulesync/skills/forge-txt2img/SKILL.md`（`image-provider`）
- 漫画コマ一括: `tools/image_provider_novel_manga_batch.py`
- 挿絵一括: `tools/image_provider_novel_illustration_batch.py`
