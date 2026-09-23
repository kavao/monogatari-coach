# cover/assets/

表紙に後載せする **ロゴ・レーベル・バーコード等の素材** を置く場所。

| 想定ファイル | 用途 |
| --- | --- |
| `title_logo.png` | 題字ロゴ（透過PNG推奨）。`cover.yaml` の `logo_asset` から参照 |
| （将来）`label_mark.png` | レーベルマーク |
| （将来）`barcode.png` | 販売用バーコード画像 |

- 発注・候補の正本は親ディレクトリの `title_logo_plan.md` / `title_logo_order.yaml`。
- 採用したら `book.yaml` の `resources.materials` と `rights.yaml` の `materials` に登録する。
