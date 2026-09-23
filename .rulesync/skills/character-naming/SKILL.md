---
name: character-naming
description: >-
  人物に名前を付けるとき、_how_to/name_creature.json などの命名資料と
  tools/json_weighted_pick.py を使って候補を組み立て、作品文脈に照らして
  不適切な候補を除外しつつ、ユーザーの明示指示を最優先で反映する。
targets: ["*"]
---

## 目的

人物名を LLM の思いつきだけで決めず、**命名資料・スキル・機械抽選**を土台にしながら、作品文脈に合う名前へ絞り込む。

- **原則**: 命名時は `_how_to/name_creature.json` などの資料を参照する。
- **抽選が必要**: 候補の選定やばらつき付けには `tools/json_weighted_pick.py` を使う。
- **そのまま採用しない自由**: 作品文脈に照らして不適切なら、スキル出力や抽選結果をそのまま採用しない。
- **最優先**: ユーザーから別途指示がある場合は、それを最優先する。

## 優先順位

人物命名の判断順は次の通り。

1. **ユーザーの明示指示**
2. **作品文脈に照らした妥当性判断**
3. **命名スキルの既定手順**

ここでいう「ユーザーの明示指示」には、次のようなものを含む。

- 使いたい名前
- 避けたい名前
- 文化圏・言語圏の指定
- 和風・洋風・中華風・幻想風などの方向性
- 音の印象、意味、文字数、頭文字、語尾の指定
- 既存キャラクターとの血縁・地域・民族の整合条件

## 参照するもの

- 命名資料: `_how_to/name_creature.json`
- 抽選ツール: `tools/json_weighted_pick.py`
- 抽選ルール: `.rulesync/skills/weighted-pick/SKILL.md`
- 作家性や文体の補助確認: `writers/.../writer_profile.md`
- 作品文脈の確認先: `proposal.md`, `design_specification.md`, `character.md`, `world.md`, `_meta.md`

## 基本手順

1. **命名条件を整理する**
   - 時代
   - 地域・文化圏
   - 種族・民族
   - 性別表現
   - 年齢感
   - 身分や職業
   - 世界観の硬さ・軽さ
   - 主要人物か脇役か
   - 血縁や同郷などの関係性

2. **ユーザーの明示指示を先に固定する**
   - 禁止条件、必須条件、語感、既定の頭文字などがあれば先に縛る。

3. **命名資料から候補帯を決める**
   - `_how_to/name_creature.json` から文化圏や役割に近い候補群を選ぶ。
   - ランダム性が欲しいときだけ `tools/json_weighted_pick.py` を使う。

4. **必要なら機械抽選する**
   - 例: 姓と名を別々に引く。
   - 例: 複数候補を `-n` でまとめて出し、その中から文脈で絞る。

5. **作品文脈でふるいにかける**
   - 世界観に対して現代的すぎないか
   - 文化圏が混ざりすぎていないか
   - 音が似た人物と衝突しないか
   - 重要人物に対して印象が弱すぎないか
   - 記号性が強すぎて不自然ではないか

6. **最終候補を提示または採用する**
   - 必要なら候補を 2〜5 個出し、差も説明する。
   - 即決してよい文脈なら、採用理由を短く添えて確定する。

## 不適切と判断する基準

次に当てはまる場合、抽選結果や既定候補をそのまま採用しない。

- 世界観と時代感に合わない
- 文化圏・民族設定と食い違う
- 同一作品内の既存人物と音や印象が近すぎる
- 役割に対して印象が軽すぎる、または重すぎる
- 読みにくい、覚えにくい、誤読されやすい
- 露骨すぎる意味づけで不自然
- ユーザーの明示指示に反する

回避するときは、**不適切な理由を短く示したうえで代替案を出す**。

## 実行例

**推奨（選定レジストリ経由）**:

```bash
python tools/novel_pick_registry.py pick naming_western_male
python tools/novel_pick_registry.py pick naming_japanese_female_heisei -n 3
```

**fallback（path 直指定）** — registry 未整備時やデバッグ用:

```bash
python tools/json_weighted_pick.py _how_to/name_creature.json -p western_last_names --json
python tools/json_weighted_pick.py _how_to/name_creature.json -p western_male_first_names -n 3 --json
python tools/json_weighted_pick.py _how_to/name_creature.json -p fantasy_male_creatures -n 5 --json
```

## エージェント向け運用

- 人物命名を頼まれたら、まずこのスキルを使う。
- ランダム性や候補抽出が必要なら、`weighted-pick` の定義に従って `tools/json_weighted_pick.py` を実行する。
- 抽選結果は**候補生成の土台**であり、最終決定そのものではない。作品文脈に合わなければ除外してよい。
- ただし、除外した場合は独断で黙って捨てず、理由を短く説明する。
- ユーザーが「この名前で」「この文化圏で」「この音は避けて」などと指定した場合は、その指示を優先する。

## 関連パス

- スキル: `.rulesync/skills/character-naming/SKILL.md`
- 命名資料: `_how_to/name_creature.json`
- 抽選スクリプト: `tools/json_weighted_pick.py`
- 関連スキル: `.rulesync/skills/weighted-pick/SKILL.md`
