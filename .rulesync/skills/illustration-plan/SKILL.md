---
name: illustration-plan
description: >-
  挿絵・表紙の計画 Markdown（Step 1）を作成する。章ごとに 0/1/複数枚を決め、
  候補3点・採用・本文アンカー・衣装 variant を illustrations/plans/ に記録する。
targets: ["*"]
---

# illustration-plan スキル

挿絵計画（Illustration Plan Mode）の Step 1 を担うスキル。本文執筆後・YAML IR 作成前に、章ごとの枚数・候補・採用を計画 MD に記録する。

## トリガー

以下のいずれかで発動する:

- 「挿絵計画を作成してください」「chapter_plan を書いてください」
- 「表紙計画を作ってください」「cover_plan を更新してください」
- Illustration Tag Mode（Step 2）開始前に計画 MD が未作成と判明したとき

## 前提条件

1. `_novel_text/novel_textXX.md` が存在する（本文が確定していること）
2. `character.md` と `tag/characters/*.yaml` が作成済み（衣装 variant を参照するため）

## 手順

### Step A — `_meta.md` §3〜§3.2 を読む

- **§3 方針**: 挿絵密度方針・章あたり既定枚数・1枚時の既定位置・候補数・優先場面・除外条件
- **§3.1 表紙**: 表紙の有無・比率・採用IR・計画状態
- **§3.2 章別割当表**: 章ごとの枚数・位置・優先シーンの確定値

§3.2 に未記入の章がある場合は、本文を参照して枚数・位置を確認しユーザーに提案する。

### Step B — `illustrations/plans/` ディレクトリを確認

- `illustrations/plans/` が存在しない場合は作成する。
- `cover_plan.md`・`chapter_plan.md` の有無を確認する。

### Step C — 表紙計画（`cover_plan.md`）

表紙が `_meta.md` §3.1 で「作る」になっている場合:

1. `_how_to.example/illustration_plan.md` の「表紙計画」節を雛形として使う。
2. 本文・design_specification・character.md を参照し、表紙の構図・登場人物・衣装 variant を記入する。
3. 候補複数案がある場合は表形式で列挙する。
4. タイトル文字節に **題字方針**（`組版` / `logo_asset` / `後回し`）を書き、`_meta.md` §3.1 と一致させる。`logo_asset` のときは続けてスキル **title-logo-plan** を案内する。
5. `_meta.md` §3.1 の「計画状態」を `計画済` に更新する。

### Step D — 章挿絵計画（`chapter_plan.md`）

`_how_to.example/illustration_plan.md` の「章挿絵計画」節を雛形として使い、章ごとに以下を記入する:

#### 枚数 1 の章

1. **枚数設定**: 枚数・位置（§3.2 の確定値）
2. **候補場面（3点）**: `_how_to.example/novelcore.md` §5 の基準（視覚的インパクト・感情ピーク・作品の売り）で3点列挙。具体的な場面・画角・登場人物を1文で。
3. **採用（1枚）**: 採用候補番号・採用理由・本文アンカー（ファイル名と引用1行）・登場人物と衣装 variant・対応IR（`illustration_XX_p01`）

#### 枚数 0 の章

1. **枚数設定**: `枚数: 0`・位置: `—`
2. **候補場面（3点）**: 記録として書いてもよい（0枚判断の根拠になる）
3. **0枚の理由**: 構図被り・回想のみ・ユーザー指定 等を1行で

#### 枚数 multiple の章

1. **枚数設定**: `枚数: N`（2以上）・位置（`章中＋章末尾` 等）
2. **候補場面（3点以上）**: multiple 枚分の候補をカバーする点数
3. **採用（複数枚）**: 表形式 `| pYY | 候補 | 位置 | 本文アンカー | 採用理由 |`

### Step E — §3.2 の進捗列を更新

各章の計画が完了したら `_meta.md` §3.2 の「計画」列を `済` にする。

### Step F — 完了報告

以下を添えて完了を伝える:

- 作成・更新したファイルパス（`cover_plan.md` / `chapter_plan.md`）
- 章ごとの採用枚数サマリー（例: 第1章:1枚、第2章:0枚、第3章:2枚）
- §3.2 で未確定の章があれば一覧
- 次のステップ: Illustration Tag Mode（Step 2）で採用分の YAML を作成

## 完了条件

- `_meta.md` §3.2 に全章の行がある（枚数・位置が確定している）
- 採用のある章はすべて `chapter_plan.md` に候補3点・採用節が書かれている
- 表紙が「作る」の場合は `cover_plan.md` が存在する
- §3.2 の「計画」列が完了章すべて `済`

## 禁止

- 計画 MD を経由せず、直接 YAML IR を作成して完了とみなしない
- `_meta.md` §3.2 を読まずに計画 MD だけ作成しない（割当表との整合が前提）
- 表紙を chapter_plan.md に混在させない（表紙は cover_plan.md と §3.1 で独立管理）

## 参照

- 創作技法雛形: `_how_to.example/illustration_plan.md`
- 作品メタ設計: `.rulesync/rules/concepts.md`「挿絵計画」「Illustration Tag Mode 作品メタ」
- Step 2 スキル: `.rulesync/skills/illustration-prompt-ir/SKILL.md`
- 操作説明: `docs/image-generation/illustration-prompt-ir.md`
