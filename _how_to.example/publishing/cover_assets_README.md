# cover/assets/

表紙に後載せする **ロゴ・レーベル・バーコード等の素材** を置く場所。
作品では `novels/<作品>/cover/assets/README.md` として同趣旨を置いてよい。

| 想定ファイル | 用途 |
| --- | --- |
| `title_logo.png` | 題字ロゴ（透過PNG推奨）。`cover.yaml` の `logo_asset` から参照 |
| （任意）`label_mark.png` | レーベルマーク |
| （任意）`barcode.png` | 販売用バーコード画像 |

- 発注・候補の正本は親ディレクトリの `title_logo_plan.md` / `title_logo_order.yaml`。
- 採用したら `book.yaml` の `resources.materials` と `rights.yaml` の `materials` に登録する。
- 操作導線: `docs/workflow/cover-composition.md`
