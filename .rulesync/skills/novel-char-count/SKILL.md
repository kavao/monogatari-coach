---
name: novel-char-count
description: "Count characters in novel Markdown using tools/novel_char_count.py (Unicode NFC code points, UTF-8)."
targets: ["*"]
---

## 目的

小説本文（`novels/**/_novel_text/novel_text*.md`）の**文字数をブレなく数える**ときに使う。推測やエディタの目視に頼らず、リポジトリ同梱の Python で数える。

## 「1文字」の定義（このプロジェクトの公式）

- ファイルは **UTF-8** で読む。
- 本文は **Unicode 正規形 NFC** に揃えたうえで、**コードポイント 1 つ = 1 文字**（Python の `len(str)` と同義）。
- **全角**の仮名・漢字・全角記号はそれぞれ **1 文字**。
- **Markdown** の `#` やリンク、**半角**の英数字・記号も、**1 コードポイントごとに 1 文字**（「文字列としてのカウント」）。
- 既定では **YAML フロントマター**（先頭の `---` … `---`）は**除外**してから数える。フロントマターも含めたい場合は `--keep-front-matter`。

合成文字（例: 基底文字＋結合文字）や絵文字は、構成するコードポイントの個数ぶんとなる。必要になったらスクリプトに拡張書記素クラスタ版を別フラグで足す。

## 実行方法

リポジトリルート（`monocri/`）で:

```bash
python tools/novel_char_count.py novels/NNN_作品タイトル
```

全作品まとめて:

```bash
python tools/novel_char_count.py --all
```

単一ファイル:

```bash
python tools/novel_char_count.py novels/NNN_作品/_novel_text/novel_text01.md
```

## `_meta.md` の章別文字数表

在庫一覧の正本は `_meta.md` I.1「章別文字数」。集計コマンドは本文を数えるだけなので、表の生成・照合は次を使う。`_meta.md` はこれらのコマンドでは書かない。

```bash
python tools/novel_meta_char_table.py render novels/NNN_作品タイトル
python tools/novel_meta_char_table.py check novels/NNN_作品タイトル
```

- 表がある作品だけ `render` を intended_meta へ写す。表が無い作品には作らない。
- `check` は表が無ければ終了コード 0。数字がずれれば 1。Gate A には繋がない。

## エージェント向け運用

- ユーザーが文字数・分量を問う、または `_meta.md` / 査証ログに**数値を書く**ときは、**可能な限り** `novel_char_count.py` を実行し、その出力を根拠にする。
- `_meta.md` の章別文字数表を更新するときは `novel_meta_char_table.py render` を使い、手で数字を作らない。
- チャット内の「だいたい○字」だけで済ませない（実行できない環境ならその旨を明記する）。

## 関連パス

- スクリプト: `tools/novel_char_count.py`、`tools/novel_meta_char_table.py`
- 対象: `novels/*/*/_novel_text/novel_text*.md`（`--all` または作品フォルダ指定時）
