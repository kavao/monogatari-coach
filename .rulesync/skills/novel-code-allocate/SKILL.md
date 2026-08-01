---
name: novel-code-allocate
description: >-
  novels/ の novel_code を tools/novel_code_allocate.py で採番（最大+1）し、
  config.md の novel_ID 整合と「資料上の別名」見出しを検証する。
targets: ["*"]
---

## 目的

`.rulesync/rules/workflow-specification.md`（命名・採番ルール）の次を、**推測せず**リポジトリ上のフォルダから機械的に行う。

- **`novel_code`** は `novels/` 直下で使われている番号の **最大 + 1** を基本とする（新規フォルダ名の接頭辞候補）。
- 作品名が資料内で揺れる場合はフォルダ名は暫定でもよいが、**`config.md` に「資料上の別名」をメモ**する — 揺れを扱うときは見出しの存在を `verify --require-alias` で確認できる。

## 採番の定義（このプロジェクトの公式）

- **対象ディレクトリ**: リポジトリルートの `novels/` 直下の**サブフォルダ**。
- **除外**: 名前が `_` で始まるもの（例: `_import`）、`.` で始まる隠しフォルダ。
- **作品フォルダ名のパターン**: `^[0-9]+_(.+)$` — 先頭の **非負整数** を `novel_code` とみなす（例: `051_タイトル` → 51、`000_...` → 0）。
- **最大値**: 上記に一致する全エントリの `code` の最大。一致しないフォルダは採番に含めず **unmatched** として警告表示。
- **重複**: 同じ `code` のフォルダが複数あっても **max は全体の最大**（運用上は重複を解消することが望ましい — スクリプトが WARNING を出す）。
- **次候補**: `next_code = max_code + 1`（作品が 0 件のときは 1）。表示用ゼロ埋め幅は `max(3, 桁数)`。

## 実行方法

リポジトリルート（`monocri/`）で:

```bash
python tools/novel_code_allocate.py
```

`scan` と同じ（一覧・max・next）:

```bash
python tools/novel_code_allocate.py scan
```

**次の接頭辞だけ**（スクリプト連携用）:

```bash
python tools/novel_code_allocate.py next
```

JSON:

```bash
python tools/novel_code_allocate.py scan --json
```

**config とフォルダ名の検証**（`novel_ID` が表形式でフォルダ先頭番号と一致するか）:

```bash
python tools/novel_code_allocate.py verify novels/051_作品名
```

資料上に別名があり、**見出し「資料上の別名」**を必須にする:

```bash
python tools/novel_code_allocate.py verify novels/051_作品名 --require-alias
```

## config.md の前提（検証用）

- **`novel_ID`**: 表の行として `| novel_ID | 051 |` 形式で記載されていること（スクリプトはこれを読む）。
- **資料上の別名**: Markdown 見出し `## 資料上の別名` または `### 資料上の別名` があると「記載あり」とみなす（本文の自由記述はスクリプトでは検査しない）。

## エージェント向け運用

- 新規作品の **`novel_code` を決める・報告する**ときは、**可能な限り本スクリプト**の `scan` / `next` の結果を正とする（実行不能な環境のみ、その旨を明記して手採番）。
- 資料取り込み後、**フォルダ名と `config.md` の整合**を `verify` で確認する。別名を扱うなら `## 資料上の別名` を追加してから `--require-alias` を通す。

## 関連パス

- スクリプト: `tools/novel_code_allocate.py`
- ルール記述: `.rulesync/rules/workflow-specification.md`（命名・採番ルール）
