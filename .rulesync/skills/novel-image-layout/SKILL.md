---
name: novel-image-layout
description: >-
  作品フォルダ内で tag/<romaji>/（キャラ画像）と manga/_assets/<manga_XX>/（漫画・コマ画像）の
  ディレクトリを tools/novel_image_layout.py で一括作成・パス列挙する。
  Forge txt2img の output_dir と組み合わせる。
targets: ["*"]
---

## 目的

`.rulesync/rules/overview.md` の **Tag Mode / Manga Tag Mode** にある「画像ストック（推奨）」を、**フォルダだけ先に機械的に用意**する。

- **タグ**: `tag/kazuki.md` と同名の **`tag/kazuki/`** に、そのキャラの生成画像をすべて保存する。
- **漫画**: `manga/manga_01.md` に対応する **`manga/_assets/manga_01/`** に、そのページのコマ画像を保存する。
- **コマ別**に分けたい場合は、同一ベースの下に **`k01`, `k02`, …**（ゼロ埋め幅は `--panels` の桁に合わせる）。

Markdown の中身の解析や画像のコピーは**行わない**（ディレクトリの scaffold / パス表示のみ）。

## 実行方法

リポジトリルート（`monocri/`）で、**作品フォルダ**を引数に取る。

**フォルダ作成**（`tag/*.md` があれば `tag/<stem>/`、`manga/manga_*.md` があれば `manga/_assets/<stem>/`）:

```bash
python tools/novel_image_layout.py scaffold novels/051_神のダンジョンβテスター
```

**コマ用サブフォルダも同時作成**（各 `manga_XX` ごとに `k01` … `k12`）:

```bash
python tools/novel_image_layout.py scaffold novels/051_神のダンジョンβテスター --panels 12
```

**作成せず、推奨 `output_dir` だけ表示**（params JSON を書くときのコピー用）:

```bash
python tools/novel_image_layout.py paths novels/051_神のダンジョンβテスター
python tools/novel_image_layout.py paths novels/051_神のダンジョンβテスター --panels 8
```

`-v` で scaffold 時に作成したパスを列挙。

## Forge との連携

- **`forge_generate`** の `output_dir` に、上記の **`tag/<romaji>`** または **`manga/_assets/<manga_XX>`**（または **`.../k03`** など）を指定する。
- `file_prefix` には同一コマ内で重複しにくいよう **`manga_01_k03`** のように章ファイル名＋コマ番号を含めると追跡しやすい（スキル **`forge-txt2img`** 参照）。
- **`tag/*.md` から Danbooru 行だけを読み、`tag/<romaji>/` にシーン別1枚ずつ**出す場合は `tools/forge_novel_tag_batch.py <作品フォルダ>`（`--dry-run` で抽出確認のみ）。
- **`manga/manga_*.md` の各コマ**（`## Page` → `## step1` 内の `tag:` … `和訳:`）を `manga/_assets/<manga_XX>/` に出す場合は `tools/forge_novel_manga_batch.py <作品フォルダ>`。ファイル名接頭辞は `manga_01_p02_k03`（ページ・コマ番号）。

## 関連パス

- 規約: `.rulesync/rules/overview.md`（§2.2.1 Tag Mode / §2.2.2 Manga Tag Mode の「画像ストック」）
- スクリプト: `tools/novel_image_layout.py`
- 画像生成: `tools/forge_generate.py`、スキル `.rulesync/skills/forge-txt2img/SKILL.md`
- 漫画コマ一括: `tools/forge_novel_manga_batch.py`
