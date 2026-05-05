# Docs

Monogatari Coach のドキュメント入口です。ルートの `README.md` は概要と最短導線に絞り、詳しい説明はこの `docs/` 配下へ整理しています。

## 目次

- [Getting Started](getting-started/index.md)
  初回セットアップ、`uv`、`.env`、主要コマンドの最短導線
- [Image Generation](image-generation/index.md)
  Forge / NovelAI / Grok の使い分け、既定値、バッチ生成
- [Manga prompt IR / パイプライン](image-generation/manga-prompt-ir.md)
  漫画ページ YAML 正本・検証・export・コマネガの合成
- [Manga tag generation（互換 Step1/Step2）](image-generation/manga-tag-generation.md)
  タグ作業用テンプレ・実例・生成モード別の運用メモ
- [Workflow](workflow/index.md)
  Monogatari Coach の各モードと制作フロー
- [Project Structure](project-structure/index.md)
  リポジトリ構成、正本の所在、主要ディレクトリ（[`_how_to/` 取り扱いガイド](project-structure/how-to-area.md) を含む）
- [Operations](operations/index.md)
  rulesync、査証ログ、ローカル試行、日常運用
- [Community](community/index.md)
  サポート、ベータ実験、推奨プラグイン、謝辞

## 正本の場所

- ルールと運用定義の正本:
  [`/.rulesync/rules/overview.md`](../.rulesync/rules/overview.md)
- スキルの正本:
  [`/.rulesync/skills/`](../.rulesync/skills/)
- 創作技法テンプレートの正本:
  [`/_how_to.example/`](../_how_to.example/)

## 読み進め方

1. 初めて触るときは [Getting Started](getting-started/index.md)
2. 画像生成や `.env` 設定を触るときは [Image Generation](image-generation/index.md)。漫画 IR のみなら [manga-prompt-ir](image-generation/manga-prompt-ir.md)、互換 Markdown の書式・タグ作業テンプレなら [manga-tag-generation](image-generation/manga-tag-generation.md)
3. 執筆フローや Mode を確認したいときは [Workflow](workflow/index.md)
4. リポジトリの規約や正本管理を確認したいときは [Project Structure](project-structure/index.md) と [Operations](operations/index.md)
