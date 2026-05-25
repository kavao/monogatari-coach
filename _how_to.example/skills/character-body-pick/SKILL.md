---
name: character-body-pick（雛形・ユーザスキル）
description: >-
  body_therapy 作品向け。_how_to/episode_mature.json から character.md の
  ボディー子ラベル候補を抽選する。実装は _how_to/tools/novel_character_body_pick.py。
  完全版手順は _how_to/skills/character-body-pick/SKILL.md。
---

## 雛形の使い方

- **正本（雛形）**: 本ファイルは `_how_to.example/skills/character-body-pick/` に置く。
- **作業用（完全版）**: 初回または更新時に **`_how_to/skills/character-body-pick/`** へコピーし、必要に応じて追記する（`_how_to.example/` は編集したくない基準として残す）。
- **Python-style lint**（`- **ラベル**:` 形式・必須項目）は公式スキル **novel-character-profile** と `tools/novel_character_md_check.py` を使う。本スキルは **候補文の抽選**のみ。

## 前提

- `_how_to/character_checklist.yaml` の `body_gender_rules` に従い、性別ごとの必須子ラベルを抽選する。
- 候補データの正本: `_how_to/episode_mature.json`（schema 2.0）。**ラベル名＝JSON トップレベルキー**。

## コマンド（リポジトリルートで）

```bash
python _how_to/tools/novel_character_body_pick.py --gender female --age-band 若者 --json
```

女性・若妖精の例:

```bash
python _how_to/tools/novel_character_body_pick.py --gender female --age-band 若妖精 --seed 42 --json
```

## 若妖精の特記事項

`_how_to/character_checklist.yaml` の **`species_notes.若妖精`** と同内容を、抽選・反映時に守る。

- **成年・表記**: 若妖精は物語上「成年」。`年齢・立場` は **`女若妖精（成年）・妖精学校通学`** のように **男若妖精／女若妖精** と成年・立場を一体で書く（男性は `男若妖精（成年）・…`）。
- **人間年齢は書かない**: 人間の○歳・○才、人間相当／換算の年齢、高校○年生だけでの言い換えは **書かない**。
- **`--age-band 若妖精`**: `episode_mature.json` のボディー分類用キー。**人間年齢の数値に変換してプロフィールへ書く用途ではない**。

## character.md への反映

- 抽選結果の `hint` を参考に、`- **ラベル**: …` を人間が読める文に整えて書く。
- 抽選だけで `character.md` を自動更新しない。lint は `python tools/novel_character_md_check.py novels/<作品> --profile plan` で別途確認する。

## 関連

- **完全版**: [`_how_to/skills/character-body-pick/SKILL.md`](../../_how_to/skills/character-body-pick/SKILL.md)（未使用膜の多軸・使い込み段階など）
- **公式 lint**: `.rulesync/skills/novel-character-profile/SKILL.md`
- **データ**: `_how_to/episode_mature.json`、`_how_to/character_checklist.yaml`
- **ユーザ Python**: `_how_to/tools/README.md`
