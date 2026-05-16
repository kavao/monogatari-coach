# 自己発展型ルールガバナンス（用語と最小カーネル）

このページは、Monogatari Coach の「自己発展型ルールガバナンス」を、**別プロジェクトにも持ち出せる**ように整理したメモです。

## これは何か（TL;DR）

**自己発展型ルールガバナンス**は、正本（Policy-as-Code）を先に固定し、チャットの指示（Instruction-driven）で運用を拡張しながら、**機械検証**と**追記ログ**で「完了」を拘束して、再現可能に発展させる運用方式です。

定義の正本は [`/.rulesync/rules/concepts.md`](../../.rulesync/rules/concepts.md) を参照してください。

## このドキュメントを使う場面

- 別リポジトリへ「Monogatari Coach 的な運用骨格」だけを移植したいとき
- ルール（正本）・手順（指示）・検証（機械チェック）・履歴（追記ログ）の役割を分けて運用したいとき

## チャットへの指示文（最小トリガー）

次のように入力すると、Monogatari Coach は「どれが正本か」「完了条件は何か」「どのツールで検証するか」を基準にして作業を進めます。

```
自己発展型ルールガバナンスの最小カーネルで運用したいです。
このリポジトリで正本ルールと実働ツールを特定して、移植用に整理してください。
```

## Monogatari Coach が行うこと（何が起きるか）

- **正本（policy）を決める**
  - `concepts.md` のような「短い概念正本」を入口にする
- **完了条件を固定する**
  - 「正本へ反映し、確認してから完了扱い」を最優先にする
- **機械検証を用意する**
  - 「揃っているか」「壊れていないか」をスクリプトで判定できるようにする
- **履歴を追記で固定する**
  - 変更の事実と理由を、上書き禁止の追記ログに残す

## 最小カーネル（移植の最短セット）

最小構成は「概念正本 + 検証 + 追記ログ」です。ここだけで、自己発展の“土台”が作れます。

- **概念正本（policy）**
  - `/.rulesync/rules/concepts.md`
  - `/.rulesync/rules/rule-authoring.md`
- **追記ログ（auditability）**
  - `tools/workspace_audit_log.py`
  - 保存先: `_workingspace/log/YYYYMM.md`, `_workingspace/diary/YYYYMM.md`
- **機械検証（verification）**
  - `tools/novel_project_check.py`（作品フォルダの必須物チェック）
  - `tools/novel_prompt_ir_validate.py`（YAML IR を運用する場合）

## 補助（必要になったら足す）

- **正本→副本の再生成（export）**
  - `tools/novel_prompt_ir_export_md.py`（YAML IR から互換 Markdown を出す）
- **ルールの配布（distribution）**
  - `corepack pnpm dlx rulesync generate`（`.rulesync/` を入口へ同期）
  - `uv run python sync_rules.py`（後方互換ラッパー経由で同じ生成を実行）

## ユーザーが確認できるもの（成果物）

- 追記ログ:
  - `_workingspace/log/YYYYMM.md`
  - `_workingspace/diary/YYYYMM.md`
- 機械検証の結果（例）:
  - `python tools/novel_project_check.py novels/NNN_作品名`
  - `python tools/novel_prompt_ir_validate.py novels/NNN_作品名`

