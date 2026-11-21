# episode（エピソード技法・横断索引・雛形）

葉は **既定では読まない**。新しい葉を足すときは `_how_to.example/_index.md` と、この README のように存在するサブカタログ入口の両方に置く。条件は行ごとでも、索引または README の冒頭注記でもよい。既存作品の selected は自動では増やさない。

エピソード設計・フック・恋愛技法は次の2系統に分かれています。ファイル名の `epsode_*` は歴史的表記（リネームしていません）。

| 系統 | 入口 | 用途 |
|------|------|------|
| general | [general/episode_.md](general/episode_.md) | 型・職業・対話・設計診断 |
| common | [common/epsode_common.md](common/epsode_common.md) | 恋愛・親愛・描写の厚み（**抜粋版**） |

general の設計技法（抽選 JSON の対象外）:

- [キャラクター・関係性](general/episode_character.md)（人物の描き分け（外見・性格・話し方）、バディー、乙女ゲーム心理、気安い関係を設計するとき）
- [物語構造・ジャンル型](general/episode_structure.md)（敵対する力・価値観の対立・軽い読み味と重いテーマの混在などの構成原則、伝奇・村ホラー・なろう型の骨格を組むとき）
- [世界観・職業・階層](general/episode_world.md)（奴隷の区分、貴族の使用人・商人・職人・ギルド・冒険者／狩人など、職業と階層の人物像を決めるとき）
- [対話・場面装置](general/episode_dialogue.md)（食事の描写で人物を見せるフード理論、途切れた会話を広げる話題生成。設計が会話を少なくしている場面では使わない）
- [社会心理参照](general/episode_social.md)（人物の振る舞いに場の力（同調・内と外・借り・正当化・理由の取り違え・肩書き・傍観・面子）を効かせたいとき。属性の傾向と追試の注意も含む。既定では読まない）
- [序盤／中盤／終盤／多人数テンポ](general/episode_tempo_ensemble.md)
- [展開エンジン／運用カード](general/episode_engine_map.md)
- [リアリティの設計](general/episode_reality.md)
- [足を引っ張るキャラクターの設計](general/episode_hindrance.md)
- [地の文モノローグの設計](general/episode_monolog.md)
- [会話の少ない場面の本文化](general/episode_sparse_dialogue.md)（口調が短い・沈黙指定・EXPRESSION が低い、会話を足さずに場面の下限へ届かせたいときだけ読む。沈黙を話題で埋める葉とは逆。既定では読まない）
- [地の文の現場音](general/episode_sound.md)（剣戟・打撃・足音・道具・布革・水火・環境の音を地の文に置きたいときだけ読む。独立行が既定。漫画の効果音とは別。既定では読まない）
- [友人類型設計（SODALITAS）](general/episode_friendship.md)
- [偽味方類型設計（AMICITIA）](general/episode_false_ally.md)
- [敵対者類型設計（MALITIA）](general/episode_antagonist.md)
- [敵の顔の庇護者類型設計（INIMICUS・エネンド）](general/episode_enend.md)
- [流れ・山・オチの構造論（PEAK）](general/episode_flow_peak_payoff.md)（主に事後の診断。プロットのアレンジでは selected に無くても読む）
- [流れ破壊と転の設計（FRACTIO）](general/episode_flow_break.md)（プロットのアレンジでは selected に無くても読む）
- [黄金律の構造（三幕構成・ヒーローズ・ジャーニー・Save the Cat）](general/episode_golden_structure.md)（作者が型を選んだときだけ。既定にしない）
- [危機脱出構成（EXITUS）](general/episode_crisis_escape.md)
- [恩義設計論（ON）](general/episode_obligation.md)
- [責任移行の人物類型設計（ONUS）](general/episode_responsibility_shift.md)
- [部活ラブコメ構成（CLUBROM）](general/episode_club_romcom.md)
- [大学サークルラブコメ類型（CIRCLEROM）](general/episode_circle_romcom.md)
- [親密さのスロープ（七つの境界軸×越境の四段階）](general/episode_intimacy_slope.md)
- [婚約からの離脱（二つの帳簿・旧配置・Phase 1〜10）](general/episode_engagement_departure.md)
- [人の心を震わせるもの／揺らぎと作者性の設計（FLUCTUATION）](general/episode_fluctuation.md)
- [子エピソードによる増量](general/episode_sub_episode.md)（加筆工程で出来事を足して分量を増やすときだけ読む。清書の削減上限到達後の追加削減分も含む。清書・規定量調整の作業中には使わない）

初回セットアップ例:

```bash
cp -r _how_to.example/episode _how_to/episode
```

### JSON 抽選 DB（general / common）

具体シチュエーションは **MD 正本 → sync → JSON** の一方向のみ（LLM による JSON 直編集はしない）。

| 系統 | MD 正本 | JSON | sync |
|------|---------|------|------|
| general フック | [general/episode_hooks.md](general/episode_hooks.md) | [general/episode_general.json](general/episode_general.json) | `episode_general_sync.py` |
| general 進行 | [general/episode_progression.md](general/episode_progression.md) | 同上 | 同上 |
| general 転換点 | [general/episode_turning_points.md](general/episode_turning_points.md) | 同上 | 同上 |
| general 対立軸 | [general/episode_conflict_axes.md](general/episode_conflict_axes.md) | 同上 | 同上 |
| general 職業 | [general/episode_occupation_hooks.md](general/episode_occupation_hooks.md) | 同上 | 同上 |
| general 対話 | [general/episode_dialogue_patterns.md](general/episode_dialogue_patterns.md) | 同上 | 同上 |
| common フック | [common/epsode_common_hooks.md](common/epsode_common_hooks.md) | [common/episode_common.json](common/episode_common.json) | `episode_common_sync.py` |
| common 進行 | [common/epsode_common_progression.md](common/epsode_common_progression.md) | 同上 | 同上 |
| common 親愛 | [common/epsode_common_affection.md](common/epsode_common_affection.md) | 同上 | 同上 |
| common 恥じらい | [common/epsode_common_shyness.md](common/epsode_common_shyness.md) | 同上 | 同上 |

```bash
python tools/episode_general_sync.py
python tools/episode_common_sync.py
python tools/novel_pick_registry.py validate
```

**相対確率**: 既定は各候補 `確率: 1.0`（均等）。作品別の重み付けは `_how_to/pick_registry/episode.yaml` で list_id を上書き（雛形: [pick_registry/episode.yaml.example](../pick_registry/episode.yaml.example)）。

プロットのアレンジの確率表 [general/episode_structure_dosing.json](general/episode_structure_dosing.json) は上の表とは別系統で、MD 正本も sync も無い（JSON が正本。数値を変えたら `_meta.version` を上げる）。スキル **novel-plot-arrange** が構造方針 rolled で読む。技法は [流れ破壊と転の設計](general/episode_flow_break.md) と [流れ・山・オチの構造論](general/episode_flow_peak_payoff.md)。

抽選は `tools/novel_pick_registry.py`（スキル **content-pick-registry**）。拡充計画: [`../../_workingspace/plans/20260705_episode-hook-json-expansion.md`](../../_workingspace/plans/20260705_episode-hook-json-expansion.md)

関連計画: [`../../_workingspace/plans/20260629_reorganize-episode-example.md`](../../_workingspace/plans/20260629_reorganize-episode-example.md)
