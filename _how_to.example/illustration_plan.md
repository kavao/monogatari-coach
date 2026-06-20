# 挿絵計画（Illustration Plan）

本ファイルは、小説の挿絵を **Step 1: 計画 Markdown → Step 2: YAML IR** の二段パイプラインで管理するための創作技法雛形です。Step 1 は人間が読む独立 Markdown（`illustrations/plans/`）であり、章ごとに **0枚／1枚／複数枚** を選べます。Step 2 は画像生成向け YAML IR（`illustrations/pages/illustration_XX_pYY.yaml`）です。**表紙（`illustration_00`）は章挿絵とは別枠**として管理します。

参照: `_how_to.example/novelcore.md` §5（候補3点）、`_how_to.example/meta.md` §3〜§3.2、スキル `illustration-prompt-ir`、`.rulesync/rules/concepts.md`「挿絵IR」。

---

## 作品内の配置

| 用途 | 計画 MD（Step 1） | 実行 IR（Step 2） |
|------|-------------------|-------------------|
| 表紙 | `illustrations/plans/cover_plan.md` | `illustrations/pages/illustration_00_pYY.yaml` |
| 章挿絵 | `illustrations/plans/chapter_plan.md` | `illustrations/pages/illustration_XX_pYY.yaml` |

番号設計: `illustration_00`＝表紙、`illustration_01`＝第1章 … `illustration_NN`＝第N章。同一章の複数枚は `p01`, `p02` … と連番。

---

# 表紙計画（cover_plan.md）

<!-- 作品フォルダに `illustrations/plans/cover_plan.md` として置く。章挿絵の chapter_plan とは別ファイル。 -->

# 表紙計画（illustration_00）

## 基本情報

- **種別**: タイトル表紙（章挿絵とは別枠）
- **採用IR**: illustration_00_p01
- **比率**: book_cover（2:3）想定
- **計画状態**: 未 / 計画済 / YAML済 / 生成済

## 構図・シーン

<!-- 1段落で具体的に。誰がどこで何をしているか、光・画角・読者に伝えたい印象まで書く。 -->

（例）雨上がりの夕暮れ、主人公が窓辺に立ち、手のひらに落ちた一滴の雨を見つめている。背後には未整理の机と、まだ書きかけの原稿。読者に「静かな決意」と「物語の入口」を感じさせるバストアップ寄りの構図。

## 登場人物・衣装

<!-- character_id と variant_id を指定。Tag Mode 正本（tag/characters/*.yaml）と整合させる。 -->

- （character_id）: variant `001_normal`
- （character_id）: variant `001_normal`

## タイトル文字

- **画像内文字**: 原則なし
- **備考**: <!-- 要る場合のみ。例: 上部30%をタイトル安全圏として空ける。ロゴ・著者名は後載せ。 -->

## 候補（任意・試作複数案）

| 案 | メモ | YAML |
|----|------|------|
| A | 窓辺・雨粒・バストアップ | illustration_00_p01 |
| B | 群像・屋上・広角 | illustration_00_p02（試作） |

---

# 章挿絵計画（chapter_plan.md）

<!-- 作品フォルダに `illustrations/plans/chapter_plan.md` として置く。章数が多い場合は `illustration_01_plan.md` 等へ分割可。 -->

# 章挿絵計画

<!-- 各章ブロックの書き方: §3.2 章別割当表の「枚数」に合わせ、該当する「採用」節だけを記入する。不要な採用節は削除。 -->

---

## 第1章（novel_text01.md）— 1枚の例

### 枚数設定

- **枚数**: 1
- **位置（1枚時）**: 章末尾
- **IR 帯**: illustration_01

### 候補場面（3点）

<!-- novelcore §5 踏襲。視覚的インパクト・感情ピーク・作品の売りが伝わる場面を、具体的な描写で3点。 -->

1. 冒頭、主人公が古いノートを開き、初めて「誰かの名前」が書かれているページに指先が止まる瞬間。斜射の朝日が紙面を照らし、指と文字の距離が近い。
2. 章中盤、狭い路地で初対面の人物とすれ違い、振り返った相手の瞳だけが画面いっぱいに入るクローズアップ。背景はボケた街灯。
3. 章末尾、二人が並んで河川敷の土手に座り、靴先だけが画面手前に入るローアングル。空は茜色、会話は少ないが距離感が縮まった余韻。

### 採用（1枚）

- **採用候補**: 3
- **採用理由**: 第1章の感情着地が「距離の変化」であり、セリフより余白で伝えたい。候補1は情報過多、候補2は第2章の対面シーンと構図が被る恐れ。
- **本文アンカー**: novel_text01.md — 「土手の草が風に揺れ、彼は隣の人物の肩の動きだけを見ていた」付近
- **登場人物・衣装**:
  - （character_id）: variant `001_normal`
  - （character_id）: variant `001_normal`
- **対応IR**: illustration_01_p01

---

## 第2章（novel_text02.md）— 0枚の例

### 枚数設定

- **枚数**: 0
- **位置**: —
- **IR 帯**: —

### 候補場面（3点）

<!-- 0枚でも候補3点は書いておくと、見送り判断の記録になる。 -->

1. 雨音が響く玄関先、濡れた靴を脱ぎながら上を見上げる主人公。水滴が顎を伝う。
2. 室内、湯気の立つマグカップを両手で包む手元アップ。背景にぼけた窓ガラスと雨筋。
3. 章末尾、相手の背中を追いかける廊下のロングショット。照明は一本だけ。

### 0枚の理由

- **理由**: 第1章末尾（河川敷・二人並び）と候補3の「余韻ロング」が構図・色調で被る。本章は会話と内面の推移が主で、挿絵より地の文で足りる。§3.2 で見送り確定。

---

## 第3章（novel_text03.md）— multiple（複数枚）の例

### 枚数設定

- **枚数**: 2
- **位置**: 章中＋章末尾
- **IR 帯**: illustration_03

### 候補場面（3点）

1. （候補1の説明）
2. （候補2の説明）
3. （候補3の説明）

### 採用（複数枚）

| pYY | 候補 | 位置 | 本文アンカー | 採用理由 |
|-----|------|------|-------------|----------|
| p01 | 1 | 章中 | novel_text03.md — 「…」付近 | （理由） |
| p02 | 3 | 章末尾 | novel_text03.md — 「…」付近 | （理由） |

---

## 第4章以降

<!-- 上記ブロックを章ごとに複製する。§3.2 章別割当表に行を追加したら、ここにも対応章を追加する。 -->

---

# 運用上の注意

## 更新順序（計画 → 割当表 → YAML）

1. **作品 `_meta.md` §3.2 章別割当表**を先に更新する（枚数・位置・優先シーンの正本）。
2. **計画 MD**（本雛形に沿った `cover_plan.md` / `chapter_plan.md`）に候補3点・採用・本文アンカー・衣装 variant を書く。
3. **YAML IR**（Illustration Tag Mode）は、計画で採用が確定した IR だけ作成する。
4. 計画 MD を更新せず YAML だけ直して完了扱いにしない。

## 表紙と章挿絵の分離

- 表紙は常に **`illustration_00` 帯**。`cover_plan.md` と §3.1 で管理する。
- 章挿絵を表紙代わりにしない（`illustration_01` を表紙にしない）。
- §3.2 章別割当表に表紙行を載せない。

## `_meta.md` §3.2 との関係

| 層 | 正本 | 役割 |
|----|------|------|
| 方針・割当 | `_meta.md` §3〜§3.2 | 作品全体の目安と **章別 0/1/複数** の確定 |
| 詳細計画 | `illustrations/plans/*.md` | 候補3点・採用理由・本文アンカー・衣装 |
| 実行 | `illustrations/pages/*.yaml` | 画像生成用 IR |

- **§3.2 の「枚数」列**が章ごとの 0 / 1 / multiple の正本。計画 MD と矛盾するときは、**直近のユーザー指示 → §3.2 表 → §3 方針フィールド** の順で優先する。
- §3.2 の「優先シーン」は計画 MD 作成時の北極星。詳細は `chapter_plan.md` へ展開する。
- 章が **0枚** のとき: YAML を作らない。計画 MD の「0枚＋理由」が Step 1 の完了条件。

## Step 2（YAML IR）への引き渡し

採用確定後、スキル `illustration-prompt-ir` に従い `illustrations/pages/` へ YAML を作成する。検証は `novel_prompt_ir_validate.py --strict-quality`。生成は `image_provider_novel_illustration_batch.py`（dry-run → 承認 → 本番）。
