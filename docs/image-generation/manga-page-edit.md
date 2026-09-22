# 漫画ページの写植と領域合成

このガイドを読むと、空の吹き出しへ日本語を後載せし、指定した範囲だけを別画像へ差し替えられます。どちらも画像 provider へは送りません。

ページ生成の既定 provider は `grok_pro` のままです。この手順は既定を切り替えません。

## 文字をどこで描くか

ページ YAML の文字方針は、実行時の `--text-mode` で次の3つから選びます。

| mode | 画像に起きること | あとの作業 |
| --- | --- | --- |
| `generate` | 画像モデルが指定した文言を描く | 字形はモデル任せ |
| `letter_later` | 空の吹き出しだけを描く | ローカル写植で文字を載せる |
| `none` | 文字も吹き出しも描かない | 文字入り完成稿にはしない |

精密な日本語は `letter_later` を使います。NovelAI で空吹き出しを出した画像にも、同じ写植コマンドを載せられます。NovelAI に字そのものを描かせる `generate` は、この写植とは別の結果になります。

## 漫画内での基本スタイル

ページ YAML の `manga.lettering` が、後載せする文字の基本スタイルです。省略時も次の既定値になります。

```yaml
manga:
  lettering:
    direction: vertical          # 基本は縦書き
    base_font_size: 30            # まず全台詞へ同じ基準サイズを試す
    size_policy: uniform_then_shrink
```

- 台詞は基本的に右の列から左の列へ縦書きします。
- `base_font_size` に入る台詞は同じサイズで配置します。
- 吹き出しに収まらない台詞だけ、写植ツールが必要最小限まで縮小します。
- 文字ブロックは、指定した吹き出し矩形の上下左右中央へ配置します。
- 縦書きでは、句読点・括弧・三点リーダーなどを縦組み用字形へ変換して描画します。ただし `？` は通常字形のままです。IRの本文は変更せず、横書きには適用しません。
- 特定の台詞だけ横書きにする場合は、台詞要素へ `writing_direction: horizontal` を明示します。
- `--font-size` はページ設定を一時的に上書きする指定です。`--size-ratio` は全台詞を意図的に縮小する指定なので、通常は使いません。

## 写植

ユーザーが空吹き出しの画像と、その画像のハッシュ付き実座標（`kind: actual`）を用意します。Monogatari Coach は IR の台詞・擬音をその矩形へ描き、`lettered.png` を保存します。設計座標（`design_projected`）のままでは写植しません。元画像の SHA-256 が違う座標ファイルは拒否します。

未配置または矩形からはみ出した文字があると、終了コードは 0 以外になり、`complete` は false です。

写植はローカル処理です。課金は発生しません。

```powershell
# 確認用の座標を検証する。hash が画像と一致しないときはここで止まる
# この例は --out が --geometry と同じため、検証済み座標で元ファイルを上書きする
# 元の座標ファイルを残す場合は、--out path/to/page.actual_geometry.bound.json のように別名にする
python tools/novel_manga_lettering.py bind-actual `
  --geometry path/to/page.actual_geometry.json `
  --image path/to/page.png `
  --out path/to/page.actual_geometry.json

# 文字を載せる。省略時はページの manga.lettering（既定は縦書き・30px）を使う
# --font-size を指定した場合だけ基準サイズを一時的に上書きする
python tools/novel_manga_lettering.py letter `
  --page novels/<作品>/manga/pages/manga_01_p01.yaml `
  --image path/to/page.png `
  --geometry path/to/page.actual_geometry.json `
  --font C:\Windows\Fonts\YuGothR.ttc `
  --out path/to/page.lettered.png `
  --result-json path/to/page.lettered.json
```

実行後、`--out` の PNG と `--result-json` の `complete` を確認します。`unplaced` と `overflow` が空のときだけ完成です。

## 領域合成

ユーザーが元ページ、同じ寸法の差し替え画像、同じ寸法のマスク PNG を用意します。マスクの値 0 は元画素を残し、0 以外だけを差し替え画像に置き換えます。Monogatari Coach は書き出したファイルを読み直し、残した画素が元ページと一致するかを検査します。

`--provider` を付けると、NovelAI を含む未対応の provider は送信前に拒否します。領域選択を API があるものとして送りません。

```powershell
# 中段など、マスクが非ゼロの範囲だけを差し替える
python tools/novel_manga_lettering.py region-edit `
  --page-image path/to/page.png `
  --replacement path/to/replacement.png `
  --mask path/to/mask.png `
  --source-sha256 <page.png の SHA-256> `
  --out path/to/page.region_edit.png
```

実行後、表示された `outside_pixels_unchanged` が true かつ `complete` が true であることを確認します。ハッシュが元画像と違うときは画像を書き出しません。

## 関連

- ページ IR と生成バッチ: [manga-prompt-ir.md](manga-prompt-ir.md)
- 画像生成の入口: [index.md](index.md)
- 文字方針の創作上の選び方: [`_how_to.example/manga.md`](../../_how_to.example/manga.md)
