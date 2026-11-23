---
name: novel-revision-branch
description: >-
  時期が過ぎた・状況が変わった作品のストーリーと設定を改訂するために、元フォルダ（051_タイトル）の
  兄弟として改訂枝（051a_タイトル）を tools/novel_branch.py で作り、一覧と差分を出す。
  範囲（骨格 / 骨格と本文 / 全体）を dry-run で見せて止まり、承認後にだけ作る。
  機械の記録（_work/）は写さない。着地の既定は並存。別の書き方・別モデルで書き比べる比較用の分岐も同じ手順で扱う。
targets: ["*"]
---

## 目的

改訂版を git のブランチではなく作品フォルダの兄弟として持ち、`novel_project_check`・執筆接続・METRON が
元と枝のどちらも普通の作品として扱えるようにする。元（旧版）は残す。

## 起動条件

- 「novels/051_作品名 を改訂版として分岐して」「時期が過ぎたので設定を改訂したい、元は残して」
- 「比較用に分岐して」（`branch_reason` は compare）
- 「051 と 051a を比較して」（差分だけ）

番号 `051` は説明用の例である。作者がフォルダを指定したときだけ分岐する。対象が取れない（「分岐して」だけ）ときは、
フォルダを解決してから範囲の確認へ進む。

## 手順（fork）

1. 元フォルダを一つに決める（パスか番号。枝からは分岐しない）。
2. 理由を決める。改訂（revision）か比較（compare）。改訂なら、時期や状況のどんな変化で切るかを口語で一言もらう
   （無ければ一言確かめる）。
3. dry-run を出して止まる。既定の範囲は skeleton_text（骨格と本文）。

   ```bash
   uv run python tools/novel_branch.py fork --from novels/051_作品名 --reason revision
   ```

   チャットには、枝の名前（未使用の最初の `a`–`z`）、範囲の三択（skeleton 骨格 / skeleton_text 骨格と本文 / full 全体）、
   写す件数と概算サイズ、写さない層、元フォルダ名を書いているファイル、WARNING を要約して返す。
4. 確認する層は作者が求めたときだけ `--include` で足す（`reader` 評価 / `backup` 旧版 / `images` 画像の実体 /
   `chronos` / `publication` 出版の lock と出力 / `archives` 圧縮ファイル。骨格の範囲では `source` `references` も）。
5. 承認後、同じ指定に `--apply` と `--note "<改訂の理由の口語>"` を付けて作る。
6. 完了の確認: 出力の `verify: OK`、`uv run python tools/novel_project_check.py novels/051a_作品名` が通ること、
   元の `_meta.md` の記録の状態。三つを確かめてから完了と報告する。
7. 査証ログに、元・枝・範囲・理由を1行追記する（スキル `workspace-audit-log`。`AUDIT_LOG | OFF` の作品は書かない）。

## 守ること

- 黙って全体を写さない。dry-run を見せずに `--apply` しない。
- `_work/`（旧 `_writing/` `_metron/` `_story_reflection_op.*` `_story_work/` `_reader/_work/`）は、範囲によらず写さない。
  写すと、未計測の本文が計測済みに見える。
- 枝の METRON / CHRONOS / AUDIT_LOG は元の値を引き継ぐ。新規作品の検査レイヤの確認はしない。
- METRON ON の元から本文を写した枝では、写した章に計測の記録が無い。完了報告に **未計測** と書き、枝で新しい章を
  書く前に後追い計測を次手にする（`novel_project_check --check-inspection-layers` が止める）。
- 改訂枝の作成は新規企画ではない。Gate B は再実施しない（設定の厚さのやり直しを明示されたときだけ検討）。
- 元のストーリー反映が途中（`TRUNK_BUSY`）なら分岐しない。終わってから分岐する。
- 同じ番号の元が複数ある番号（`AMBIGUOUS_TRUNK`。例: 既存の `001_` が複数）からは分岐しない。番号の重複を作者が解消してからにする。
- 元フォルダ名を書いているファイル（`config.md` の「資料上の別名」など）は自動で書き換えない。dry-run の一覧を作者へ返す。
- 以後の執筆・清書・評価は、明示されたフォルダだけを対象にする。「051 を書いて」は元、「051a を書いて」は枝。
  曖昧なら一言確かめる。

## 一覧と差分

```bash
uv run python tools/novel_branch.py list novels/051_作品名
uv run python tools/novel_branch.py diff 051 051a --layer text,design
```

- 差分は層ごとの変更ファイル（内容差・片方だけ）、本文の章別・合計文字数（`novel_char_count.py` と同じ数え方）、
  設計書・人物表の見出し・番号項・欄の数の増減だけをチャットへ返す。本文の全文は出さない。
- 評価は各フォルダの `_reader/` に別に保存する。片方の点数をもう片方へ写さない。

## 第1版でしないこと

- 枝から元への反映（promote）、章単位の取り込み（absorb）、元の直しを枝へ追従させること。頼まれたら
  「第1版では並存まで」と返し、必要なファイルを作者が選んで手で写す場合は、元の該当ファイルを先に退避する。
- 10本以上の枝、`051ab_`・`051_a_` の形、`novels/` の子ディレクトリ分割。

## 関連

- 横断仕様: `workflow-specification.md`「改訂枝（作品分岐）」
- 採番・検証: スキル `novel-code-allocate`（`novel_code_allocate.py verify` が branch / parent_ID を見る）
- 人間向け: `docs/workflow/novel-revision-branch.md`
