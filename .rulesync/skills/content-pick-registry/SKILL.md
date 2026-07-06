---
name: content-pick-registry
description: >-
  Pick Registry（選定レジストリ）の list_id 解決と抽選運用。
  分割 YAML（pick_registry/）をマージし、tools/novel_pick_registry.py で
  list / show / pick / validate する。低レイヤ抽選は weighted-pick のまま分離。
targets: ["*"]
---

## 目的

命名・プロフィール補助・エピソード／トロープ候補など、**JSON リストへの抽選入口**を `list_id` で宣言的に登録する。公式ルールは本スキルと **concepts.md「選定レジストリ」** に汎用機構だけを書き、mature／body 等の具体内容は **`_how_to/pick_registry/`** に閉じる。

## 正本の所在

| 層 | パス |
|----|------|
| 雛形（public のみ） | `_how_to.example/pick_registry/`（`_index.yaml` + `character.yaml` + `episode.yaml`） |
| ユーザ運用 | `_how_to/pick_registry/`（`mature.yaml` 等・visibility: user） |
| 作品別（任意） | `novels/<作品>/pick_registry/work.yaml` |
| trope JSON（public 初版） | `_how_to.example/episode/general/episode_general.json`、`_how_to.example/episode/common/episode_common.json` |

マージ規則: `_index.yaml` の `merge_order` に従い **後勝ち**。`list_id` は全フラグメント横断で一意。

## スキル分担

| スキル | 役割 |
|--------|------|
| **weighted-pick** | `json_weighted_pick.py` + JSON `--path` 直指定（registry 未知でも動く低レイヤ） |
| **content-pick-registry**（本スキル） | 分割 registry マージ、`list_id` 解決、`novel_pick_registry.py` |
| **character-naming** | 命名の優先順位・ふるい。抽選は `naming_*` list_id または weighted-pick fallback |
| **novel-character-profile** | `character.md` 構造 lint。抽選節は持たず、checklist の `suggested_pick_lists` を参照するのみ（任意） |

## CLI（`tools/novel_pick_registry.py`）

```bash
# 登録一覧（public のみ）
python tools/novel_pick_registry.py list --visibility public

# 定義確認
python tools/novel_pick_registry.py show naming_western_male

# 抽選（内部で json_weighted_pick または novel_character_pick を呼ぶ）
python tools/novel_pick_registry.py pick episode_hook_general --seed 42

# 整合性（source 存在・path 到達・list_id 重複なし）
python tools/novel_pick_registry.py validate

# 作品別 registry を merge に含める（_meta 自動解決は未実装・CLI フックのみ）
python tools/novel_pick_registry.py --novel novels/NNN_作品名 list
```

## visibility

| 値 | 公式 docs に載せるか |
|----|---------------------|
| `public` | ○（list_id と説明のみ） |
| `user` | ×（機構の説明のみ。mature 固有 ID は `_how_to/pick_registry/mature.yaml`） |
| `work` | ×（将来拡張） |

## ユーザ fragment の有効化

既定 merge は **`_how_to.example/pick_registry`** → **`_how_to/pick_registry`**（存在するディレクトリ・ファイルのみ）。`_index.yaml` の `fragments.mature: mature.yaml` は **スロット宣言** であり、ファイルが無ければスキップされる（clone 直後に `mature.yaml` が無いのは正常）。

| 用途 | コマンド |
|------|----------|
| public 一覧（公式 docs の手順例はこれに限定） | `python tools/novel_pick_registry.py list --visibility public` |
| user 確認（`mature.yaml` 配置後） | `list --visibility user` または `list --prefix mature_` |
| 整合性 | `python tools/novel_pick_registry.py validate` |

**セットアップ正本**: `_how_to.example/pick_registry/README.md`  
**テンプレ**: `_how_to.example/pick_registry/mature.yaml.example` を `_how_to/pick_registry/mature.yaml` にコピーして編集（example 直下を `mature.yaml` にリネームしない）。

checklist の **`suggested_pick_lists`** と mature 向け手順の索引は **`_how_to/skills/_index.md`**（例: character-body-pick、episode-mature-pick）。本スキルおよび公式 docs には **episode_mature.json の path 直書きを載せない**。

## character.md との接続

- `_how_to/character_checklist.yaml` の profile に **`suggested_pick_lists: [list_id, ...]`** を載せられる。
- `tools/novel_character_md_check.py` は checklist の文字列を **HINT** として表示する（body_therapy 固定分岐なし）。
- ユーザスキル完全版は **`_how_to/skills/_index.md`** から辿る（公式スキルから具体スキル名・パスを直書きしない）。

## 関連

- 横断: `.rulesync/rules/concepts.md`「選定レジストリ」「公式スキルとユーザスキルの接続」
- 低レイヤ: `.rulesync/skills/weighted-pick/SKILL.md`
- 命名: `.rulesync/skills/character-naming/SKILL.md`
- プロフィール lint: `.rulesync/skills/novel-character-profile/SKILL.md`
- 操作: `docs/tools/index.md`（`novel_pick_registry.py`）