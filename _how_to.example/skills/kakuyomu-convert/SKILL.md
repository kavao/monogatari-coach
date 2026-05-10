---
name: kakuyomu-convert（雛形・ユーザスキル）
description: >-
  作品フォルダの kakuyomu.csv に基づき、_novel_text の本文へカクヨムルビ記法を機械挿入し
  _novel_text_re に出力する。実装は _how_to/tools/kakuyomu_ruby_apply.py。完成稿の置き場は
  _novel_text_re。カクヨム記法の正本は公式ヘルプ。ユーザ向けの最短手順は USER_HINTS.md。
---

## 雛形の使い方

- **正本（雛形）**: 本ファイルは `_how_to.example/skills/kakuyomu-convert/` に置く。
- **作業用**: 初回または更新時に、同フォルダを **`_how_to/skills/kakuyomu-convert/`** へコピーして使う（`_how_to.example/` は編集したくない基準として残す）。
- **2点だけの要点**: [`USER_HINTS.md`](USER_HINTS.md)（**コピー**／**カクヨムプラグイン**のリスト）。
- **CSV サンプル（コピー元）**: [`kakuyomu.csv.example`](kakuyomu.csv.example) — 例として **`コピー`** と **`カクヨムプラグイン`** の2行のみ。実作品では `match` を本文の表記に合わせて増やす。

## このスキルが指す運用

1. **（任意）ミラー**: `novels/<作品>/_novel_text/*.md` を `novels/<作品>/_novel_text_re/` にコピーする。  
   ― スクリプトが **`--input-subdir _novel_text` → `--output-subdir _novel_text_re`** のとき、入力が `_novel_text` なら**ワンステップでルビ付き稿を `_novel_text_re` に書ける**ため、ミラーは必須ではない。
2. **CSV 整備**: 同じ作品フォルダに **`kakuyomu.csv`** を置く（列定義は下記）。
3. **実行**: `_how_to/tools/kakuyomu_ruby_apply.py` を実行する。
4. **確認**: `novel_char_count.py` や Read で `_novel_text_re` を確認する。

## 技法・記法の正本

- **ルビの書き方・長さ制限・縦線** … [カクヨムヘルプ「ルビや傍点を付ける」](https://kakuyomu.jp/help/entry/notation)
- **CSV で指定するのは「本文に出てくる親文字」と「読み」** … スクリプトが `親《よみ》` または `｜親《よみ》` に整形する。

## `kakuyomu.csv`

- **エンコーディング**: UTF-8（BOM 可、Excel 互換で `utf-8-sig` 読み）。
- **必須列**
  - **`match`** … 本文検索に使う文字列（作品内の表記そのもの）。
  - **`reading`** … `《》` 内に入れる読み。
- **省略可**
  - **`mode`** … `auto`（既定）または `pipe`。
    - **`auto`**: 親が「漢字のみ」の近似なら `親《読み》`。それ以外は `｜親《読み》`。
    - **`pipe`**: 常に全角縦線付き `｜親《読み》`。
- **列名の別名**（互換）: `match` の代わりに `keyword` / `from` / `surface`。`reading` の代わりに `ruby` / `yomi`。
- **同一 `match` が複数行**: **後の行が優先**。
- **適用順**: **長い `match` から先**（短い語が長い語の一部になる場合のため）。

サンプルは同フォルダの [`kakuyomu.csv.example`](kakuyomu.csv.example) を参照。

## コマンド（リポジトリルートで）

**確認のみ（書き込みなし）**

```powershell
python _how_to/tools/kakuyomu_ruby_apply.py `
  --novel-dir novels/<作品フォルダ名> `
  --dry-run --verbose
```

**本番（`_novel_text` → `_novel_text_re`）**

```powershell
python _how_to/tools/kakuyomu_ruby_apply.py `
  --novel-dir novels/<作品フォルダ名>
```

**入力をミラー済み `_novel_text_re` にし、上書きだけしたい場合**

```powershell
python _how_to/tools/kakuyomu_ruby_apply.py `
  --novel-dir novels/<作品フォルダ名> `
  --input-subdir _novel_text_re `
  --output-subdir _novel_text_re
```

## パス規約

| 役割 | パス |
|------|------|
| CSV（既定） | `novels/<作品>/kakuyomu.csv` |
| 読み元（既定） | `novels/<作品>/_novel_text/` |
| 書き先（既定） | `novels/<作品>/_novel_text_re/` |
| スクリプト | `_how_to/tools/kakuyomu_ruby_apply.py` |

## 禁止・注意

- **`_novel_text` を直接ルビ加工しない**運用にするときは、必ず **出力を `_novel_text_re`** に限定する（既定どおり）。
- 親 **20 文字・ルビ 50 文字**を超える行は **WARN** を出すが処理は続ける（公式上限に注意）。
- 既に `親《` の形が付いている語は **二重ルビを避けるためスキップ**する。
- **短命の試行スクリプト**は `tools_temp/`。本スクリプトは **`_how_to/tools/`** に固定する。

## 関連

- **`USER_HINTS.md`** … ユーザ向け最短リスト（コピー／カクヨムプラグイン）
- **`_how_to/tools/README.md`** … ユーザ用 Python の位置づけ
- **`.rulesync/skills/novel-char-count/SKILL.md`** … 文字数確認
- **`.rulesync/rules/concepts.md`** … 「共有ツールとユーザ用 Python」
