---
name: novel-character-profile
description: >-
  character.md を作成・更新・点検するときに、登場人物プロフィールを
  `- **ラベル**:` 形式で揃え、_how_to/character_checklist.yaml と
  tools/novel_character_md_check.py で構造 lint する。
targets: ["*"]
---

## 目的

Plan Mode の人物プロフィールを、人間が読みやすいまま、Tag Mode 前の書き漏れ検出にも使える形へ整える。

`character.md` は物語プロフィールの全集として扱う。見た目・生成用の機械正本は引き続き `tag/characters/<character_id>.yaml` であり、このスキルは Markdown 側のラベル不足を検知する。

## 書き方

- 先頭見出しは `# 登場人物プロフィール` を推奨する。既存互換として `# 登場人物` も lint では許容される。
- キャラクター見出しは `## 名前（よみがな）` または `## 名前（役割）` のように全角カッコ付きにする。
- 本文は `- **ラベル**: 内容` を基本形にする。
- 子項目が必要な項目は、次のようにインデントした箇条書きで書く。

```markdown
- **服装**:
  - **普段着**: 白いシャツと濃紺のパンツ。
  - **外出時**: 薄手のコートと歩きやすい靴。
```

## チェックリスト

- 同梱デフォルト: `_how_to.example/character_checklist.yaml`
- ユーザー運用正本: `_how_to/character_checklist.yaml`
- 作品別上書き: `novels/<作品>/character_checklist.yaml`

読み込み優先は、環境変数 `MONOCRI_CHARACTER_CHECKLIST`、`_how_to/character_checklist.yaml`、`_how_to.example/character_checklist.yaml`。作品別 YAML があれば最後にマージする。

## lint

Plan 完了時:

```bash
python tools/novel_character_md_check.py novels/<作品> --profile plan
```

Tag Mode 前に見た目だけ確認したいとき:

```bash
python tools/novel_character_md_check.py novels/<作品> --profile visual
```

移行猶予をなくして厳密に見るとき:

```bash
python tools/novel_character_md_check.py novels/<作品> --profile plan --strict
```

表形式は既定では WARN。`--strict` または checklist の `table_policy: error` で ERROR にする。

不足項目の追記案や表形式の変換案を見たいとき:

```bash
python tools/novel_character_md_check.py novels/<作品> --profile plan --suggest
```

`--suggest` はファイルを書き換えない。表示された Markdown を、人物設定に合わせて加筆・調整してから `character.md` へ反映する。TODO のまま保存しない。

執筆前チェックに含めるとき:

```bash
python tools/novel_project_check.py novels/<作品> --require-character-structure --character-profile plan
```

JSON で提案も含めたいときは `--character-suggest --json` を併用する。

## ボディー候補の抽選（任意）

`body_therapy` 作品で `episode_mature.json` から候補文を引くときは、**ラベル名＝JSON トップレベルキー**（schema 2.0）として扱う。

```bash
python tools/novel_character_body_pick.py --gender female --age-band 若者 --json
```

旧キー名（`女性の体型` 等）はツール内の `episode_path` 正規化でのみエイリアス。新規実装ではラベル名をそのままキーに使う。

## 関連

- Plan Mode: `.rulesync/skills/novel-planning/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- Tag Mode の機械正本: `.rulesync/skills/manga-prompt-ir/SKILL.md`
