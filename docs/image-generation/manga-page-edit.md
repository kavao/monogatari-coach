# 漫画ページの写植と領域合成

このガイドを読むと、吹き出しを **ページ生成時に描かせる** 手順と、字形が崩れたときだけ使う後載せ写植、NovelAI で割り当てが崩れたときだけ使う後処理枠、指定した範囲だけを別画像へ差し替える操作が分かります。写植と枠合成は画像 provider へ送りません。

ページ生成の既定 provider は `grok_pro` のままです。この手順は既定を切り替えません。横断既定は **写植なし** です。Grok / GPT Image の吹き出し指定は、作品の後載せ写植フラグで分かれます。`しない` と未記入のときはモデルが元の吹き出しへ日本語を描きます（`generate`）。`する` ときは空泡のあと写植します。CLI で `--text-mode` を付けたときは、その指定が勝ちます。

## このドキュメントを使う場面

1. **どんな場面で使うか** — 漫画ページ YAML の台詞を画像へ載せるとき。標準はページ生成の字を残します。Grok などで空泡を描かせたあと写植するとき。NovelAI V5 で話者へ吹き出しを割り当てたあと、字形が崩れたときだけ写植するとき。割り当てが崩れた NovelAI 画像だけ、泡なし再生成とローカル枠へ退避するとき。
2. **チャットへの指示文** — 「Grok で generate の dry-run」「Grok で letter_later の dry-run」「NovelAI で generate の dry-run」「NovelAI で letter_later の dry-run」「NovelAI local で1ページ」「この PNG に写植」と入力すると、Monogatari Coach は自動的に dry-run またはローカル写植の手順へ進みます。本番生成は承認後だけです。NovelAI ページの先の手は T1 と同じ `generate` です。標準はモデル字を残します。`letter_later` と `local` と写植は明示指示です。
3. **Monogatari Coach が行うこと** — 能力キー（解決済み model / profile）を見て描き方を分けます。Grok / GPT Image / Nano Banana は native のままです。NovelAI はページへ `text, speech bubble` を足し、話者の character slot へ `白い吹き出し「台詞」` を載せます。このタグと日本語の slot 語は Grok / GPT へ送りません。`local` は NovelAI かつ `page_render_plan` だけです。Grok 画像へローカル枠は重ねません。
4. **ユーザーが確認できるもの** — dry-run の `capability_key` / `text_mode` / `bubble_frame_mode`、保存 PNG、`.local_frame.json`（退避時）、`lettered.json` の `complete`。

## 原則

吹き出しの意味（誰が何を言うか）はページ YAML の `text` が正本です。描き方だけレンダラ能力で切り替えます。全モデルを後処理そろえにはしません。標準はページ生成時の字を残します。NovelAI は、参照作例 T1 と同じく話者へ吹き出しを割り当ててページ生成します。後載せ写植は字形が崩れたとき、または作品が `する` のときだけです。後処理枠は割り当てが崩れたときの退避です。

| 経路 | いつ使うか | 生成時 | あと |
| --- | --- | --- | --- |
| native（既定） | Grok / GPT Image / Nano Banana | 写植しない作品は `generate`（元の吹き出しに字）。写植する作品は空泡の `letter_later` | 空泡なら **actual** へ写植。`generate` なら写植しない |
| NovelAI 割り当て（先に使う） | NovelAI V5 のページ | T1 と同じ `generate`。ページに `text, speech bubble`。話者 slot に `白い吹き出し「台詞」` | 割り当てを目視。読めるなら完了。崩れたときだけ **actual** へ写植 |
| NovelAI 空泡 | 空の吹き出しだけ欲しいとき | 明示の `letter_later` | 空泡の **actual** へ写植 |
| local（退避） | NovelAI の割り当てが崩れたとき | 泡・文字を抑止した clean PNG（`text_mode=none`） | sidecar で枠 → actual → 写植 |

`layout_geometry` はコマ枠だけです。吹き出し位置の推測には使いません。

## 能力表（暫定）

コンパイラは provider 名文字列ではなく、解決済み model / profile の能力キーを見ます。OpenRouter は輸送路であり、能力は中のモデルです。未登録の model は送信前に停止します。`strong` は実測が揃うまでの暫定です。

| 能力キー | 主な入口 | native 吹き出し | 後処理推奨 |
| --- | --- | --- | --- |
| `grok_imagine_2` | `grok` / `grok_pro` | native（暫定） | しない |
| `gpt_image_2` | OpenAI 直結または OpenRouter の GPT Image 2 | native（暫定） | しない |
| `nano_banana_2` | OpenRouter の Nano Banana 2 | native（導入後・暫定） | しない |
| `novelai_v5` | NovelAI `nai-diffusion-5-*` | T1 割り当てを先（不安定） | 枠は native が崩れたときだけ |

`nai-diffusion-4-5-*` は `novelai_v5` ではありません。Vibe 参照が付くと V4.5 にピンされ、V5 のページ実験は停止します。

`--bubble-frame-mode` は `provider` または `local` だけです。既定は `provider`。`auto`（能力から自動選択）は未実装です。既定を `auto` にする判断、dry-run での選択結果表示、未登録停止の文言は、導入するときに同時に書きます。今は別承認です。

provider の領域編集 API（Inpaint 等）は未接続です。`--provider` 付きの `region-edit` は送信前に拒否します。

## native（Grok / GPT Image）

**写植しない**作品（横断既定）では、ユーザーが `generate` でページを生成する → Monogatari Coach は元の吹き出しに日本語が入った画像を保存します。後載せ写植はしません。

**写植する**作品では、ユーザーが `letter_later` でページを生成する → Monogatari Coach は空泡付き画像を保存する → ユーザーが泡の実座標（`kind: actual`）を用意する → 写植コマンドが `lettered.png` を出します。

作品 `_meta.yaml` の `manga_lettering.enabled` が `false` または未設定のとき、`--text-mode` 省略は `generate` です。`true` のとき省略は `letter_later` です。ページ YAML の `text_mode` があるときは、作品フラグよりページ側が勝ちます。CLI 明示は変えません。この方針は `page_render_plan` だけでなく、legacy の Grok ページ台詞行の有無にも使います。

Grok / GPT Image / Nano Banana の吹き出しが失敗したときは、その画像へローカル枠を重ねません。手動停止です。これらの PNG を `local` 再生成の入力にもしません。

精密ページ生成の dry-run と本番は、課金前確認のため `--dry-run` を先にします。

```powershell
# 確認（dry-run）— 標準。capability_key=grok_imagine_2 と text_mode=generate を見る
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider grok_pro `
  --page-compiler page_render_plan --text-mode generate `
  --min-page 1 --max-page 1 --dry-run

# 本番（承認後。--dry-run を外す）
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider grok_pro `
  --page-compiler page_render_plan --text-mode generate `
  --min-page 1 --max-page 1
```

写植する作品だけ、`--text-mode letter_later` に変えます。実行後、`manga/_assets/<manga_XX>/comic/` の画像と JSON を確認します。後載せが必要なときだけ下の「写植」節です。

## NovelAI の割り当て（先に使う）

既定のページ provider は Grok のままです。NovelAI でページを出すときは `--page-compiler page_render_plan` の opt-in です。Grok 経路へ切り替えて再送しません。

手本は `outputs/novelai_manga_tests` の T1 です。受入例は `tools/manga_prompt_ir/examples/p4_compare/manga/_assets/manga_01/comic/manga_01_p01_step1page_20260923_014501_1819231479.png` です。ユーザーが NovelAI ページを指示する（`--text-mode` 省略も同じ） → Monogatari Coach はページへ `text, speech bubble` を足し、話者の character slot へ `白い吹き出し「台詞」` を載せます → 吹き出し付き PNG を保存します。吹き出しの位置と話者への割り当てを正とします。標準はモデル字を残します。字形が崩れたときだけ下の「写植」節で載せ直します。このタグと日本語 slot 語は Grok / GPT へ送りません。

`--bubble-frame-mode` は既定の `provider` のままです。`local` は付けません。V5 では `--novelai-portion-id none` が必要です。`.env` の Vibe 参照が付くと V4.5 になり、`novelai_v5` 未登録で止まります。

`step1-pages` / `step2-pages` で `--aspect-ratio` を省略すると `manga_b5_portrait`（832×1216）です。config の 1024×1024 には落としません。コマ生成（`step1-panels`）の正方形既定は従来どおりです。

```powershell
# 確認（dry-run）— capability_key=novelai_v5、text_mode=generate、bubble_frame_mode=provider、image_size=832x1216 を見る
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider novelai `
  --page-compiler page_render_plan `
  --novelai-portion-id none --min-page 1 --max-page 1 --dry-run

# 本番（承認後。--dry-run を外す）
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider novelai `
  --page-compiler page_render_plan `
  --novelai-portion-id none --min-page 1 --max-page 1
```

実行後、保存 PNG に吹き出しがあり、話者へ向いているかを目視します。割り当てが崩れたときは、同じ画像へ枠を重ねず、空泡の `letter_later` または local 退避を使います。割り当てが足りて台詞が読めるなら完了です。字形が崩れて写植するとき、モデル字が泡の中に残っている場合は、写植の前に泡の内側を空けます。枠そのものは描き直しません。

## NovelAI の空吹き出し（明示するとき）

空の吹き出しだけ描かせて後で写植するときは `--text-mode letter_later` を付けます。話者 slot は「白い吹き出し」だけになり、台詞本文は送りません。

```powershell
# 確認（dry-run）— text_mode=letter_later を見る
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider novelai `
  --page-compiler page_render_plan --text-mode letter_later `
  --novelai-portion-id none --min-page 1 --max-page 1 --dry-run
```

## NovelAI フォールバック（local・空泡が崩れたとき）

NovelAI ページの `local` は、上の割り当て生成が崩れたときの退避です。先の手順の代わりに最初から `local` にはしません。Grok 経路へ切り替えて再送しません。

`local` は `text_mode=none` に固定します。`letter_later` / `generate` との併用は停止します。プレースホルダ空泡は描きません。人物 slot の「白い吹き出し」も local では使いません。

V5 の local では `--novelai-portion-id none` が必要です。`.env` の Vibe 参照が付くと V4.5 になり、`novelai_v5` 未登録で止まります。

`step1-pages` / `step2-pages` で `--aspect-ratio` を省略すると `manga_b5_portrait`（832×1216）です。config の 1024×1024 には落としません。コマ生成（`step1-panels`）の正方形既定は従来どおりです。

```powershell
# 確認（dry-run）— capability_key=novelai_v5、text_mode=none、image_size=832x1216 を見る
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider novelai `
  --page-compiler page_render_plan --bubble-frame-mode local `
  --novelai-portion-id none --min-page 1 --max-page 1 --dry-run

# 本番（承認後）
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --manga-stem manga_01 --source step1-pages --provider novelai `
  --page-compiler page_render_plan --bubble-frame-mode local `
  --novelai-portion-id none --min-page 1 --max-page 1
```

実行後、clean PNG と同名の `.json`、`.local_frame.json`（`local` + `none` + `bubbles_suppressed` + `source_sha256`）を確認します。記録と PNG のハッシュが違うと枠描画は止まります。

### ローカル枠

ユーザーが正規化座標の sidecar（`bubbles[]`。ページ YAML の第二スキーマではない）を用意する → Monogatari Coach は PNG へ白枠を描き、別ファイルへ保存します。入力は上書きしません。JPEG は受けません。件数は sidecar と台詞 ID が一致していること。画像認識で補正しません。

```powershell
# 枠を描く。generation-json は .local_frame.json でよい。入力 PNG は上書きしない
python tools/novel_manga_lettering.py render-bubbles `
  --page novels/<作品>/manga/pages/manga_01_p01.yaml `
  --bubbles path/to/page.bubbles.yaml `
  --generation-json path/to/page.local_frame.json `
  --image path/to/page.png `
  --out path/to/page.bubbles.png `
  --result-json path/to/page.bubbles.json
```

実行後、`frame_count` と `complete` を確認します。`dialogue` は speech、`narration` は narration、`monologue` は thought の枠として描き、`sfx` は枠なしの文字領域として保持します。続けて、枠付きPNGの出力ハッシュを使って `actual` 座標を確定してから写植します。`design_projected` のままでは写植しません。

枠付きPNGを入力にして、`bubbles` の設計座標を画像ハッシュ付き `actual` geometryへ確定します。`--generation-json` には `render-bubbles` の `--result-json` を渡します。これにより、actual は枠付きPNGに結び付き、別画像への誤適用を停止できます。

```powershell
python tools/novel_manga_lettering.py bind-bubbles-actual `
  --page novels/<作品>/manga/pages/manga_01_p01.yaml `
  --bubbles path/to/page.bubbles.yaml `
  --generation-json path/to/page.bubbles.json `
  --image path/to/page.bubbles.png `
  --out path/to/page.bubbles.actual.json
```

実行後、`kind=actual`、`texts` 件数、`source_sha256` が枠付きPNGのハッシュと一致することを確認します。

Grok など native の `letter_later` PNG と、NovelAI の `generate` / `letter_later` PNG は、この枠コマンドの入力にしません。枠は `local` の clean PNG だけです。NovelAI の `generate` PNG は、枠を重ねずに actual 写植の入力にします。

## 文字をどこで描くか

ページ YAML の文字方針は、実行時の `--text-mode` で次の3つから選びます。第4の mode はありません。

| mode | 画像に起きること | あとの作業 |
| --- | --- | --- |
| `generate` | 画像モデルが吹き出しを話者へ割り当て、中に字を描く | 標準はここで完了。字形が崩れたときだけ NovelAI 等で actual 写植 |
| `letter_later` | 空の吹き出しだけを描く（`bubble_frame_mode=provider` のみ） | ローカル写植で文字を載せる |
| `none` | 文字も吹き出しも描かない（`local` はこれ） | 枠合成のあと写植 |

標準は `generate` の字を残します。後載せが必要なときだけ写植コマンドで載せます。Grok の空泡は `letter_later` のあとです。NovelAI で写植するときも割り当て付き `generate` のあとです。泡の内側にモデル字が残っているときは、写植の前に空けます。割り当て自体が崩れたときだけ `none`＋ローカル枠のあとに写植します。

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

ユーザーが吹き出しの実座標（`kind: actual`）と、その画像の SHA-256 を用意します。空泡でも、NovelAI の割り当て済み泡でも同じです。作品が写植 `する` とき、またはモデル字が読めないときに使います。Monogatari Coach は IR の台詞・擬音をその矩形へ描き、`lettered.png` を保存します。設計座標（`design_projected`）のままでは写植しません。元画像の SHA-256 が違う座標ファイルは拒否します。NovelAI の `generate` PNG でモデル字が残っているときは、先に泡の内側を空けてから写植します。同じ画像へローカル枠は重ねません。

未配置または矩形からはみ出した文字があると、終了コードは 0 以外になり、`complete` は false です。

写植はローカル処理です。課金は発生しません。`letter` は `bind-actual` と同じく、座標ファイルの `source_sha256` が対象画像と一致しないと停止します。画質や枠の顔被りは別課題です。`complete` は座標へ収まったことだけを表します。

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
