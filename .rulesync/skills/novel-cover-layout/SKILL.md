---
name: novel-cover-layout
description: >-
  cover.yaml の編集・book_cover_review・lock・book_export による reader-proof 生成と
  _meta.md §3.1／§7 の同期を行う。題字は組版 text または logo_asset。
---
# novel-cover-layout スキル

表紙レイアウトと出版 proof までのゲート。題字ロゴの計画・生成自体は **title-logo-plan**。

## トリガー

- 「表紙合成して proof を出してください」
- 「cover.yaml を整えて」「reader-proof を出して」
- 題字採用後、または組版題字の確定後

## 前提

1. `book.yaml` / `rights.yaml` がある（Publishing Package Phase 1）。
2. 表紙を作る作品では approved な cover 挿絵（`illustration_00` 等）がある。
3. `_meta.md` §3.1 の **題字方針** が `組版` または `logo_asset`（`後回し` なら proof 題字は未完成と明示）。

## 手順

1. `_meta.md` §3.1・§7 と既存 `cover.yaml` を読む。無ければ `_how_to.example/publishing/cover.yaml.example` から起こす。
2. 題字方針に合わせて title レイヤーを `text` または `logo_asset` にする。
3. `python tools/book_cover_review.py novels/<作品> --target reader --gate writing` で確認する。
4. export 前: `book_review.py --gate export --target paper` → `book_lock.py` → `book_diff.py --against lock`。
5. `book_export.py --target paper --profile bunko|jis_b5` で interior / reader-proof を出す。
6. `book_preflight.py` で errors=0 を確認する。
7. `_meta.md` §7（と必要なら §3.1）を同期する。

## 完了条件

`workflow-specification.md`「出版完成目安」に同じ:

1. 表紙絵 §3.1 が `生成済`（またはなし＋理由）
2. 題字レイヤーが方針どおりで cover review が通る
3. rights 登録
4. lock 一致
5. interior + reader-proof、preflight errors 0
6. `_meta.md` §7 同期

## 禁止

- `cover.yaml` 無しのまま「表紙合成完了」としない（表紙なし作品は §7 で `—`）
- dry-run／承認ルールを画像生成で破らない（ロゴ生成時）
- 印刷 wrap cover / EPUB を本スキルの完了に含めない

## 参照

- 操作: `docs/workflow/cover-composition.md`、`publishing-package.md`、`paper-proof-export.md`
- 概念: `.rulesync/rules/workflow-specification.md`「表紙合成と題字」「出版完成目安」
- 題字ロゴ: `.rulesync/skills/title-logo-plan/SKILL.md`
