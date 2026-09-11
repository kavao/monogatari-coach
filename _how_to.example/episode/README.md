# episode（エピソード技法・横断索引・雛形）

エピソード設計・フック・恋愛技法は次の2系統に分かれています。ファイル名の `epsode_*` は歴史的表記（リネームしていません）。

| 系統 | 入口 | 用途 |
|------|------|------|
| general | [general/episode_.md](general/episode_.md) | 型・職業・対話・設計診断 |
| common | [common/epsode_common.md](common/epsode_common.md) | 恋愛・親愛・描写の厚み（**抜粋版**） |

general の設計技法（抽選 JSON の対象外）:

- [序盤／中盤／終盤／多人数テンポ](general/episode_tempo_ensemble.md)
- [展開エンジン／運用カード](general/episode_engine_map.md)
- [リアリティの設計](general/episode_reality.md)
- [足を引っ張るキャラクターの設計](general/episode_hindrance.md)
- [地の文モノローグの設計](general/episode_monolog.md)

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

抽選は `tools/novel_pick_registry.py`（スキル **content-pick-registry**）。拡充計画: [`../../_workingspace/plans/20260705_episode-hook-json-expansion.md`](../../_workingspace/plans/20260705_episode-hook-json-expansion.md)

関連計画: [`../../_workingspace/plans/20260629_reorganize-episode-example.md`](../../_workingspace/plans/20260629_reorganize-episode-example.md)
