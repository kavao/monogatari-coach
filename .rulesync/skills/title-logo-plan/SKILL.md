---
name: title-logo-plan
description: >-
  表紙に後載せする題字ロゴの計画・発注・採用を行う。cover/title_logo_plan.md と
  title_logo_order.yaml を正本にし、採用後に cover.yaml を logo_asset へ差し替える。
---
# title-logo-plan スキル

題字方針が **`logo_asset`** の作品向け。表紙絵（`illustration_00`）とは別ジョブでロゴ単体を作る。

## デフォルト方針（ライトノベル・コミック的スタイルの確立）

- **方向性**: 指定がない限り**横書き（`horizontal`）タイトル主体**を既定（デフォルト）とする。ライトノベルや現代商業書籍で一般的な横タイトル配置（上部横幅いっぱいや中央上部など）を基本とする。
- **世界観情報の引き渡し**: 単なるテキスト指定にとどまらず、作品の雰囲気・テーマ・キーワード・作中キーアイテム・配色イメージなどの世界観情報をAIプロンプト（`title_logo_order.yaml`）へしっかりと引き渡し、作品にマッチした魅力的なデザインロゴを生成させる。

## トリガー

- 「題字ロゴを計画してください」
- 「タイトルロゴを作って」「title_logo を進めて」
- `_meta.md` §3.1 の題字方針が `logo_asset` で、計画または asset が未整備のとき

## 前提

1. `_meta.md` §3.1 で **題字方針: logo_asset** が明示されている（未決なら先にユーザーと決める）。
2. 表紙絵または `cover.yaml` の title box／safe_areas が分かる（仮 box でも可。横書き既定のため上部横長エリアを第一候補とする）。
3. 雛形: `_how_to.example/publishing/title_logo_plan.md` と `title_logo_order.yaml.example`。

## 手順

1. `_meta.md` §3.1、`proposal.md`、`design_specification.md`、`illustrations/plans/cover_plan.md` を読み、タイトル文字列だけでなく世界観・トーン・キーアイテム・テーマ色を把握する。
2. `cover/` を用意し、`title_logo_plan.md` に横書き既定の候補3点・世界観トーン・box・チェックリストを書く。
3. `title_logo_order.yaml` を雛形から起こし、作品の世界観ディテール（`world_context` / `style` / `color`）と横書きプロンプト案を入れる。
4. 画像生成はスキル **image-provider**（`forge-txt2img`）に従い **`--dry-run` → 承認 → 本番**。
5. 採用PNGを `cover/assets/title_logo.png` に置き、`cover.yaml` の title を `type: logo_asset` に差し替える（組版 text と二重にしない）。
6. `book.yaml` / `rights.yaml` の materials に登録する。
7. `_meta.md` §3.1 の題字ロゴ状態を更新し、§7 の題字レイヤーを `logo_asset` にする。
8. 続けてスキル **novel-cover-layout** で review → lock → export を行う（同一セッションでよければ続けてよい）。

## 完了条件

- `cover/title_logo_plan.md` に採用が記録されている
- `cover/assets/title_logo.png` が存在する
- `cover.yaml` の title が `logo_asset` で asset を指す
- rights / materials に登録済み
- `_meta.md` §3.1 題字ロゴ状態が `採用済`

## 禁止

- 表紙絵 IR にタイトル文字を焼いてロゴ完了としない
- dry-run なし・承認なしで本番生成しない
- 方針が `組版` の作品に無理に logo を必須としない

## 参照

- 概念: `.rulesync/rules/concepts.md`「表紙合成と題字」
- 操作: `docs/workflow/cover-composition.md`
- レイアウト続き: `.rulesync/skills/novel-cover-layout/SKILL.md`
