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

## エージェント向け運用

- ユーザーが文字数・分量を問う、または `_meta.md` / 査証ログに**数値を書く**ときは、**可能な限り本スクリプトを実行**し、その出力を根拠にする。
- チャット内の「だいたい○字」だけで済ませない（実行できない環境ならその旨を明記する）。

## 関連パス

- スクリプト: `tools/novel_char_count.py`
- 対象: `novels/*/*/_novel_text/novel_text*.md`（`--all` または作品フォルダ指定時）
