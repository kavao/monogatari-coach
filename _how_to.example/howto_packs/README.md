# 創作技法パック（案 C）

葉の列挙（案 A）の短縮記法。**既定では読まない・適用しない。** Gate B で `pack_id` を書いた作品だけ展開する。既存作品の selected には自動では付けない。

作業用 `_how_to/howto_packs/<pack_id>.yaml` があれば、その1ファイルを自己完結として使う。無ければ標準 `_how_to.example/howto_packs/<pack_id>.yaml`。合成しない。

| pack_id | 発動 | 中身 |
|---|---|---|
| [general](general.yaml) | 作品プロファイルが一般のとき、Gate B で選んだ場合 | 最小葉（novelcore / naming / novel_structure） |
| [mature](mature.yaml) | mature を選んだ場合 | 同じ最小葉。mature 専用エピソードは pack_add または selected |
| [body_therapy](body_therapy.yaml) | body_therapy を選んだ場合 | 同じ最小葉。ユーザスキルはパック外 |

パックに無い葉は `pack_add` または selected に書く。パックから外す葉は `pack_exclude`。ジャンル葉（`genre/*`）はパックに入れない。
