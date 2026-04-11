---
name: weighted-pick
description: >-
  JSON リストから tools/json_weighted_pick.py で均等または確率フィールドに基づき乱数選択する。
  LLM のあいまい抽選に頼らず Python で再現可能にする。
targets: ["*"]
---

## 目的

企画・分類・名前リストなど、**JSON に定義した候補から1件（または複数回）選ぶ**ときに、**必ず `tools/json_weighted_pick.py` を実行**し、結果を正とする。推測や会話上の「だいたいの確率」だけで選ばない。

## 動作の定義（公式）

- **対象**: UTF-8 の JSON ファイル、または `--eval` で渡した JSON 文字列、または標準入力（`-`）。
- **パス（階層）**: `--path`（`-p`）に **ドット区切り**で辞書キーを上から辿る（例: `western_last_names`、`食べ物.メイン候補`）。**末端が配列**になっているノードで抽選する。`tools/fixtures/weighted_sample.json`のようにネストが深い場合も、**該当リストまでのキーを `.` でつなげばよい**。  
  - **キー名に `.` が含まれる**と分割できない（現状未対応。キー名を変えるか、JSON を加工する）。
  - **多段抽選**（例: 先に「メイン候補」でラーメンが出たら、続けて「スープ系」を引く）は、**コマンドを段階ごとに実行**し、2回目以降の `--path` を手元の結果に合わせて組み立てる（自動チェーンはしない）。
- **長い解説文・「曖昧な記載」**: JSON の説明文は抽選に使わない。**配列の形と数値フィールド**だけが効く。
- **末端が配列のとき**
  - **文字列・数値など非オブジェクトの混在配列**: **均等**に1件（`mode: uniform`）。
  - **オブジェクトの配列**（各要素が辞書）:
    - 次のいずれかのキーから非負の数値として重みを読む（先に見つかったキーを採用）:  
      `確率`, `相対確率`, `weight`, `Weight`, `重み`, `prob`, `probability`, `ウェイト`  
      文字列の `"30%"` や `"30"` も可能。`相対確率` が 0.4 のような小数でも合計で正規化される。
    - **全要素**に解釈可能な重みがある → **重み付き**（`mode: weighted`）。重みの合計は100でなくてもよい（合計で正規化）。
    - **どの要素にも重みがない** → **均等**（`mode: uniform`）。
    - **一部だけ重みがある／重みの合計が0／解釈できない値がある** → データが曖昧なので **配列全体を均等**（`mode: uniform_fallback`）。
- **末端がオブジェクトのとき**: キー名を **均等**に1つ選び、`picked` にキー、`value` に値（`mode: uniform_dict_keys`）。
- **再現性**: `--seed 整数` を付けると**同じコマンドを何度実行しても同じ結果**になる（検証・再現用）。**毎回ちがう抽選にしたいときは `--seed` を付けない**こと。
- **複数回（`-n`）**: 同一プロセス内では **1 つの乱数生成器で連続抽選**する（かつて `-n` ごとに `Random()` を作り直しており、短時間では同じシードになり得た問題を解消）。

## 実行例

`_how_to/name_creature.json` の苗字リストから均等に1件:

```bash
python tools/json_weighted_pick.py _how_to/name_creature.json -p western_last_names --seed 42 --json
```

オブジェクト配列で重み付き（例は `tools/fixtures/weighted_sample.json`・「今日の天気」）:

```bash
python tools/json_weighted_pick.py tools/fixtures/weighted_sample.json -p 今日の天気 --json
```

`weighted_sample.json` の階層例（食べ物・メイン10種 → 確率付きリスト）:

```bash
python tools/json_weighted_pick.py tools/fixtures/weighted_sample.json -p 食べ物.メイン候補 --json
```

ラーメンだけさらに細分化（スープ系の内訳）:

```bash
python tools/json_weighted_pick.py tools/fixtures/weighted_sample.json -p 食べ物.ラーメン.スープ系 --json
```

同じくラーメン配下のトッピング追加（別リスト・重み付き）:

```bash
python tools/json_weighted_pick.py tools/fixtures/weighted_sample.json -p 食べ物.ラーメン.トッピング追加例 --json
```

短い JSON を直接渡す（ファイル不要・食べ物のミニ例。`items` 配列に `food` と `確率`）。**bash / PowerShell 共通**で、JSON 全体をシングルクォートで囲むとエスケープが簡潔です。

```bash
python tools/json_weighted_pick.py --eval '{"items":[{"food":"ramen","確率":40},{"food":"curry","確率":60}]}' -p items --json
```

標準入力:

```bash
type data.json | python tools/json_weighted_pick.py - -p some.path
```

複数回（ブートストラップや表のサンプル列）:

```bash
python tools/json_weighted_pick.py _how_to/name_creature.json -p fantasy_male_creatures -n 5 --json
```

## エージェント向け運用

- 「ランダムに選ぶ」「確率に従う」指示が出たら、**本スクリプトの出力**（`picked` と `mode`）をチャットに引用する。
- 階層 JSON では、**該当する配列まで `--path` で明示**してから実行する（パス誤りは `KeyError` で分かる）。

## 関連パス

- スクリプト: `tools/json_weighted_pick.py`
- 重み付き例: `tools/fixtures/weighted_sample.json`
- 大容量リスト例: `_how_to/name_creature.json`
