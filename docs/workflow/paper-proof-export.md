# 紙書籍 proof PDF（Phase 2A）

Phase 1 の出版パッケージを lock した後、本文・付属原稿・採用済み挿絵から **縦書き本文 proof PDF** と、表紙を先頭に付けた**閲覧用 proof PDF**を作る手順です。本文や画像を複写・更新せず、派生物だけを `_publication_output/` に保存します。

これは入稿前の確認用 proof です。印刷所固有の PDF/X-1a、CMYK、表1・背・表4をつないだ最終カバーは、この工程の対象外です。

## 前提

1. `book.yaml` / `rights.yaml` / 本文 / 採用画像が揃っている。
2. `python tools/book_review.py novels/NNN_作品名 --gate export --target paper` が error 0 である。
3. `python tools/book_lock.py novels/NNN_作品名 --target paper` を実行済みである。
4. `python tools/book_diff.py novels/NNN_作品名 --against lock` の added / removed / changed が空である。

依存パッケージは `requirements.txt` または `pyproject.toml` にある `reportlab` と `pypdf` です。ReportLab は Unicode の TrueType フォントを埋め込め、pypdf は生成PDFのページ・リソース検査に使います。詳細は [ReportLab の公式フォントガイド](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/) と [pypdf の公式ドキュメント](https://pypdf.readthedocs.io/en/stable/) を参照してください。

## 生成

```bash
# 文庫サイズ（ISO A6・105 × 148 mm）
python tools/book_export.py novels/NNN_作品名 --target paper --profile bunko

# JIS B5（182 × 257 mm）
python tools/book_export.py novels/NNN_作品名 --target paper --profile jis_b5
```

出力先は次のようになります。`<build-id>` は実行時刻を基に生成されます（既定は `paper-<profile>-…`）。

```text
novels/NNN_作品名/_publication_output/<build-id>/
├─ manifest.json     # lock hash・原稿順・画像配置・組版プロファイル
├─ interior.pdf      # 本文 proof（選択したプロファイル寸法）
├─ reader-proof.pdf  # 表紙 + interior.pdf の閲覧・配布確認用 proof
└─ preflight.json    # 出力検査の結果
```

`_publication_output/` は再生成できる派生物であり、Git の追跡対象外です。出版の正本は引き続き `book.yaml`、`rights.yaml`、`_novel_text/`、`book_matter/`、`illustrations/` です。

## 成果物と用途

- `interior.pdf`: 奇数ページ開始・本文挿絵・埋め込みフォントを確認する内面 proof。紙書籍の本文組版を検討するときに使う。
- `reader-proof.pdf`: `book.yaml` の `type: cover` で `status: approved` の表紙アートを1ページ目に置き、`interior.pdf` を続けた閲覧・PDF配布確認用のproof。作品に **`cover.yaml` がある場合**は、題字・著者レイヤーを表紙絵の上に合成した **layered cover** を1ページ目にする（`type: text` 組版／`type: logo_asset` 題字ロゴのどちらも可）。手順は [表紙合成・題字ロゴ](cover-composition.md) を参照。
- `cover.pdf`: **この工程では生成しない**。表1・背・表4をつないだ印刷所入稿用カバーは、後述の印刷所仕様が確定してから別工程で生成する。

出力先を固定したいときは `--build-id` を使います。

```bash
python tools/book_export.py novels/NNN_作品名 --profile bunko --build-id first-bunko-proof
```

同じ build ID が既にある場合、上書きせず停止します。

## 組版プロファイル

### `bunko`（文庫 / ISO A6）

- 仕上がり寸法: 105 × 148 mm（ISO A6。文庫本に近い確認用寸法）
- 余白（proof）: 天/地 12 mm、のど 14 mm、小口 11 mm
- 本文: 右から左へ送る縦書きの proof 組版
- その他の原稿順・directive・挿絵 dpi・閲覧用表紙の扱いは `jis_b5` と同じ

`book.yaml` の `format.trim_size: 文庫` は書誌メタです。PDF 寸法は **`--profile bunko`** で決めます。

### `jis_b5`

- 仕上がり寸法: JIS B5、182 × 257 mm
- 余白（proof）: 天/地/のど 18 mm、小口 15 mm
- 本文: 右から左へ送る縦書きの proof 組版
- 原稿順: `frontmatter → chapters → backmatter`
- `start_page_policy: odd_page`: 必要なら空白ページを挿入して奇数ページから開始
- `<!-- scene: ... -->`: 本文に出力しない構造アンカー
- `<!-- illustration: id -->`: `book.yaml` で `status: approved` の画像を本文内の独立ページへ配置
- 挿絵: 実効 250 dpi 以上を preflight で確認
- 閲覧用表紙: `reader-proof.pdf` の1ページ目に approved な `type: cover` asset があること、本文 proof より1ページ多いことを preflight で確認

proof 用の日本語フォントは、既定では Windows の Yu Mincho を使い、TrueType として PDF へ埋め込みます。別の埋め込み可能な `.ttf` を明示するときは、環境変数を使います。

```powershell
$env:MONOCRI_BOOK_FONT = "C:\fonts\NotoSerifJP-Regular.ttf"
python tools/book_export.py novels/NNN_作品名 --target paper --profile bunko
```

proof フォントはローカル確認用です。最終入稿では、フォントライセンスを `rights.yaml` に記録し、印刷所の指定に合わせて確定してください。

## 再検査

既存の build を再検査するときは、次を実行します。

```bash
python tools/book_preflight.py novels/NNN_作品名/_publication_output/<build-id> --target paper
```

preflight は次を検査します。

- 全ページが選択したプロファイルの仕上がり寸法であること
- 本文フォントが埋め込まれていること
- `odd_page` 指定の原稿が奇数ページから始まること
- directive で参照した挿絵が想定ページに存在すること
- 挿絵の実効解像度が 250 dpi 以上であること
- `reader-proof.pdf` が表紙1ページ + `interior.pdf` であり、表紙ページに画像が存在すること

`PF-X01` は、PDF/X と印刷所固有のカラープロファイルが未検証であることを示す proof 固有の warning です。これだけならproofは有効ですが、印刷所への入稿はまだ行いません。

## 最終カバーを始める条件

表1・背・表4を一体化した入稿カバーには、次の情報が必要です。

- 印刷所のテンプレート
- 綴じ方式、本文用紙、紙厚
- 組版後の確定ページ数
- 表紙用紙、カラー設定、PDF規格・カラープロファイル

これらが未確定の間は、`illustrations/_assets/illustration_00/` の表紙アートを正本として保ち、巻カバーPDFを推測で作りません。
