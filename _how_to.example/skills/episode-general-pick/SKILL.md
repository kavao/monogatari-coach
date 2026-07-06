---
name: episode-general-pick
description: >-
  一般向けエピソード技法（general / common）のフック・進行候補を
  選定レジストリの list_id から抽選する雛形手順。
---

## 位置づけ

| 領域 | 正本 |
|------|------|
| 技法 MD | `_how_to.example/episode/general/`、`_how_to.example/episode/common/` |
| 抽選 DB（初版） | `episode_general.json`（フック・進行・対話の型）、`episode_common.json`（恋愛フック・関係進行） |
| list_id 宣言 | `_how_to.example/pick_registry/episode.yaml` |
| 抽選 CLI | 公式 `tools/novel_pick_registry.py` |

実運用で拡張するときは `_how_to/pick_registry/episode.yaml` で上書き・追加する。

## いつ使うか

- Plan Mode で一般向けショートエピソードのたたき台を組み立てたいとき
- 恋愛・親愛系（common）か、汎用型（general）かを選んでフックを振りたいとき

## 抽選コマンド例

```bash
python tools/novel_pick_registry.py validate
python tools/novel_pick_registry.py list --domain episode --visibility public

# 冒頭フック（general: 帰省、依頼、違和感、異界）
python tools/novel_pick_registry.py pick episode_hook_general
python tools/novel_pick_registry.py pick episode_hook_general_visit
python tools/novel_pick_registry.py pick episode_hook_general_discovery
python tools/novel_pick_registry.py pick episode_hook_general_supernatural

# 進行パターン（general: 調査、対立）
python tools/novel_pick_registry.py pick episode_progression_general
python tools/novel_pick_registry.py pick episode_progression_general_conflict

# 恋愛・親愛フック（common: 再会、世話）
python tools/novel_pick_registry.py pick episode_hook_common
python tools/novel_pick_registry.py pick episode_hook_common_care

# 関係進行（common: 揺れ、秘密）
python tools/novel_pick_registry.py pick episode_progression_common
python tools/novel_pick_registry.py pick episode_progression_common_secret

# 口調
python tools/novel_pick_registry.py pick profile_speech_pattern
```

最後の `profile_speech_pattern` は character domain だが、口調候補として character.md 補助に使える。

## 関連

- 公式: `.rulesync/skills/content-pick-registry/SKILL.md`
- 索引: `_how_to.example/skills/_index.md`、`_how_to/_index.md`