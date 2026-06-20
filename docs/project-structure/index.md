# Project Structure

Monogatari Coach の主要ディレクトリと、どこを正本として扱うかをまとめます。

## 正本の所在

- ルール・運用定義:
  `/.rulesync/rules/`
  - 横断概念の正本: `/.rulesync/rules/concepts.md`
  - ルール作成規約: `/.rulesync/rules/rule-authoring.md`
- スキル:
  `/.rulesync/skills/`
- 創作技法テンプレート:
  `/_how_to.example/`

`/.codex/` や `/_how_to/` は参照・作業領域として使えますが、恒久的な更新の主編集先ではありません。
`AGENTS.md` / `CLAUDE.md` は LLM 別入口として扱い、主編集先は `.rulesync/` 側に置きます。

## 主要ディレクトリ

- `writers/`
  作家プロフィール
- `novels/`
  作品本体
- `novels/_import/`
  既存作品や外部出力の取り込み口
- `_how_to/`
  ローカル調整用の創作技法ファイル（準ルール・作法領域。ユーザーが直接編集する前提）→ [取り扱いガイド](how-to-area.md)
- `_how_to.example/`
  創作技法テンプレートの正本
- `tools/`
  正規運用スクリプト
- `tools_temp/`
  ローカル試行用の一時領域
- `_workingspace/`
  作業計画、査証ログ、横断ナレッジ
- `config/`
  画像生成などの設定
- `docs/`
  GitHub 上で見やすく整理した案内文書

## 作品フォルダの基本

作品フォルダ `novels/NNN_タイトル/` には主に次が入ります。

- `proposal.md`
- `design_specification.md`
- `config.md`
- `character.md`
- `world.md`
- `_novel_text/`
- `_reader/`
- `tag/`
- `manga/`
- `_meta.md`

詳細なファイル規約は [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) を参照してください。

## `_workingspace/` の役割

`_workingspace/` は、作品本文ではなく、プロジェクト横断の計画・履歴・判断理由を管理する領域です。

| 領域 | 役割 |
|------|------|
| `_workingspace/plans/` | これから行う作業予定、改修順、チェックリスト（トピック計画は `YYYYMMDD_<slug>.md`） |
| `_workingspace/log/YYYYMM.md` | そのセッションで何をしたかの作業事実 |
| `_workingspace/diary/YYYYMM.md` | 次回以降も効く判断理由、好み、運用知見 |

査証ログと日記の追記には `tools/workspace_audit_log.py` を使います。詳しいコマンドは [Tools](../tools/index.md) を参照してください。
