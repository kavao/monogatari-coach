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

**外見の書き方（軽量化）**

- `character.md` は全身部位の Danbooru タグを網羅する場所ではない。
- **外見**: 1〜2文の散文で第一印象を書く。
- **外見の個性**: キャラクターを見分ける核を **子項目3件以上**（推奨3〜5件）書く。執筆前チェック（`plan` profile）でも必須。
- 髪・目・肌・衣装 variant などの詳細タグは Tag Mode で `tag/characters/*.yaml` に展開する。`外見の個性` は執筆者・読者・Tag Mode の橋渡しとして扱う。

## 書き方

- 先頭見出しは `# 登場人物プロフィール` を推奨する。既存互換として `# 登場人物` も lint では許容される。
- キャラクター見出しは `## 名前（よみがな）` または `## 名前（役割）` のように全角カッコ付きにする。
- 本文は `- **ラベル**: 内容` を基本形にする。
- **身長**は全キャラ必須。`- **身長**: 約○○cm` のように数値または明確なサイズ感を書く（例: `小柄`, `高身長`）。Tag Mode では `tag/characters/<id>.yaml` の `appearance.height` に写す。
- 子項目が必要な項目は、次のようにインデントした箇条書きで書く。

```markdown
- **外見の個性**:
  - 黒髪ミディアムボブと、落ち着いた灰色の瞳が第一印象に残る
  - 端的な態度と、考え込むと親指でノートの角をなぞる癖
  - 制服の袖口を少し長めにしている細やかなこだわり
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
python tools/novel_project_check.py novels/<作品>
```

JSON で提案も含めたいときは `--character-suggest --json` を併用する。

## ボディー候補の抽選（body_therapy・任意）

`episode_mature.json` からボディー子ラベルの候補文を引く処理は **ユーザスキル** に分離した。

- 完全版: `_how_to/skills/character-body-pick/SKILL.md`
- 実装: `_how_to/tools/novel_character_body_pick.py`

チャットでユーザスキルを明示してから使う（公式 agent スキルには載らない）。

## 関連

- Plan Mode: `.rulesync/skills/novel-planning/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- Tag Mode の機械正本: `.rulesync/skills/manga-prompt-ir/SKILL.md`
