# Pick Registry（選定レジストリ）セットアップ

`list_id` ごとに「どの JSON のどの path から何を引くか」を宣言し、`tools/novel_pick_registry.py` で解決・抽選する仕組みです。雛形は **`_how_to.example/pick_registry/`**（public のみ）、ユーザ拡張は **`_how_to/pick_registry/`**（Git 管理外）に置きます。

横断定義: [`.rulesync/rules/concepts.md`](../../.rulesync/rules/concepts.md)「選定レジストリ」、公式スキル **content-pick-registry**。

---

## 一般ユーザ（既定・追加作業不要）

clone 直後は **`_how_to.example/pick_registry/`** だけが merge されます。全年齢向けの naming / episode 抽選はこれで足ります。

```bash
python tools/novel_pick_registry.py validate
python tools/novel_pick_registry.py list --visibility public
python tools/novel_pick_registry.py pick episode_hook_general
python tools/novel_pick_registry.py pick naming_japanese_female_heisei
```

一般エピソードの手順雛形: [`../skills/episode-general-pick/SKILL.md`](../skills/episode-general-pick/SKILL.md)。

---

## なぜ `_how_to/pick_registry/mature.yaml` が clone に無いか

| 理由 | 説明 |
|------|------|
| **`.gitignore`** | `_how_to/*` は原則 Git 管理外（ユーザ運用正本） |
| **公開境界** | mature / body 向け list_id は一般 clone ・公式 docs に載せない |
| **カスタム仕様** | `_index.yaml` の `fragments.mature` は **スロット宣言**。ファイルが無ければ merge 時にスキップされ、**欠落ではない** |

`python tools/novel_pick_registry.py validate` が public の list_id だけで **exit 0** なのは正常です。

---

## mature / body 利用者の有効化手順

1. **`_how_to/` を用意**（未作成なら `python howto_init.py` または `_how_to.example/` からコピー）
2. **`_how_to/pick_registry/`** ディレクトリを作成
3. 本ディレクトリの **`mature.yaml.example`** を **`_how_to/pick_registry/mature.yaml`** にコピー
4. `list_id`・`source`・`path` を自分の運用に合わせて編集（JSON トップレベルキーは `_how_to/episode/mature/episode_mature.json` の `_meta.pick_paths_examples` 等を参照）
5. 検証:

```bash
python tools/novel_pick_registry.py validate
python tools/novel_pick_registry.py list --prefix mature_
python tools/novel_pick_registry.py show mature_episode_opening
```

**PowerShell（例）:**

```powershell
New-Item -ItemType Directory -Force -Path _how_to\pick_registry
Copy-Item _how_to.example\pick_registry\mature.yaml.example _how_to\pick_registry\mature.yaml
```

**注意:** `mature.yaml.example` を **`_how_to.example/pick_registry/mature.yaml` にリネームしない**こと（example 直下の `mature.yaml` は一般 merge に混入する）。

---

## checklist との接続

`_how_to/character_checklist.yaml` の profile に **`suggested_pick_lists`** を載せると、lint が list_id を HINT します（path は載せない）。

```yaml
profiles:
  body_therapy:
    extends: plan
    suggested_pick_lists:
      - mature_body_profile_female_young
    suggested_skill: _how_to/skills/character-body-pick/SKILL.md
```

---

## ユーザスキル

mature 向けの組み合わせ手順・一括抽選は **完全版ユーザスキル** を参照します。入口は **`_how_to/skills/_index.md`**（例: character-body-pick、episode-mature-pick）。公式 `.rulesync/skills/` には mature 具体 path を載せません。

---

## トラブルシュート

| 症状 | 確認 |
|------|------|
| `list_id が見つかりません` | `_how_to/pick_registry/mature.yaml` 未配置、または typo |
| `validate` で source 不在 | `_how_to/episode/mature/` 未コピー、または `source` パス誤り |
| user list が 0 件 | `mature.yaml` 未作成、または `visibility: user` 以外 |
| public だけ欲しいのに mature が見える | `_how_to/pick_registry/mature.yaml` を削除または `list --visibility public` を使う |

---

## ファイル一覧（本ディレクトリ）

| ファイル | merge | 説明 |
|----------|-------|------|
| `_index.yaml` | ○ | merge_order・fragments 定義 |
| `character.yaml` | ○ | public・命名・profile |
| `episode.yaml` | ○ | public・general/common トロープ |
| `mature.yaml.example` | **×** | コピー用テンプレ（user fragment） |
| `episode.yaml.example` | **×** | episode list_id 上書き・追加テンプレ（user） |
| `README.md` | — | 本ファイル |
