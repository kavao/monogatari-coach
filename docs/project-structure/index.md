# Project Structure

Monogatari Coach の主要ディレクトリと、どこを正本として扱うかをまとめます。

## 正本の所在

- ルール・運用定義:
  `/.rulesync/rules/`
- スキル:
  `/.rulesync/skills/`
- 創作技法テンプレート:
  `/_how_to.example/`

`/.codex/` や `/_how_to/` は参照・作業領域として使えますが、恒久的な更新の主編集先ではありません。

## 主要ディレクトリ

- `writers/`
  作家プロフィール
- `novels/`
  作品本体
- `novels/_import/`
  既存作品や外部出力の取り込み口
- `_how_to/`
  ローカル調整用の創作技法ファイル
- `_how_to.example/`
  創作技法テンプレートの正本
- `tools/`
  正規運用スクリプト
- `tools_temp/`
  ローカル試行用の一時領域
- `_workingspace/`
  査証ログや横断ナレッジ
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
