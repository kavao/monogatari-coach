# Docs

**Monogatari Coach** は、AI（Claude / Codex など）を使った小説執筆を一元管理するフレームワークです。企画・設計・執筆・清書・書評・画像生成まで、制作のすべてのフェーズをチャット上の指示だけで進められます。

このドキュメントは、Monogatari Coach を使う人向けの操作マニュアルです。ルートの `README.md` は概要と最短導線に絞り、詳しい説明はこの `docs/` 配下へ整理しています。

---

## 目次

- [Getting Started](getting-started/index.md)
  初回セットアップ、`uv`、`.env`、主要コマンドの最短導線
- [Rulesync の固定運用](rulesync.md)
  固定版バイナリの取得、ルール生成、整合確認
- [開発者向け検証コマンド](developer-verification.md)
  変更種別ごとの確認、コミット前の総合ゲート、実クライアント観測
- [Image Generation](image-generation/index.md)
  Forge / NovelAI / Grok の使い分け、既定値、バッチ生成
- [Manga prompt IR / パイプライン](image-generation/manga-prompt-ir.md)
  漫画ページ YAML 正本・検証・export・コマネガの合成
- [Manga tag generation（互換 Step1/Step2）](image-generation/manga-tag-generation.md)
  タグ作業用テンプレ・実例・生成モード別の運用メモ
- [挿絵・表紙（計画 → IR → 生成）](image-generation/illustration-prompt-ir.md)
  挿絵計画 MD（Step 1）→ YAML IR（Step 2）→ 画像生成の二段パイプライン
- [Workflow](workflow/index.md)
  Monogatari Coach の各モードと制作フロー
- [ユーザスキル（プラグイン相当）](workflow/user-skills.md)
  `_how_to/skills/` と `_how_to.example/skills/` の関係、ツールの置き場（例: カクヨムルビ）
- [Source Material Intake](workflow/source-material-intake.md)
  既存資料を作品フォルダへ展開するときの手順と保存先
- [Planning](workflow/planning.md)
  企画書・設計書・人物・世界観を揃えて執筆前確認へ進む流れ
- [Publishing Package（Phase 1）](workflow/publishing-package.md)
  読者向けの付属原稿、挿絵・権利・奥付の点検、入稿入力の lockfile 管理
- [表紙合成・題字ロゴ（Phase 1.5）](workflow/cover-composition.md)
  題字方針（組版／logo_asset）、`cover.yaml`、題字ロゴ計画から reader-proof まで
- [紙書籍 proof PDF（Phase 2A）](workflow/paper-proof-export.md)
  lock 済みの出版入力から縦書き本文 proof（`bunko` / `jis_b5`）を生成し、PDF を機械検査する手順
- [Reader Output](workflow/reader-output.md)
  下読み・書評・興味判定の保存先とチャット要約の扱い
- [Project Structure](project-structure/index.md)
  リポジトリ構成、正本の所在、主要ディレクトリ（[`_how_to/` 取り扱いガイド](project-structure/how-to-area.md) を含む）
- [Tools（ツールリファレンス）](tools/index.md)
  `tools/` 配下の全スクリプトと CLI 例、rulesync・howto_init・tools_temp の操作方法
- [Community](community/index.md)
  サポート、ベータ実験、推奨プラグイン、謝辞

## 正本の場所

- ルールと運用定義の正本:
  [`/.rulesync/rules/overview.md`](../.rulesync/rules/overview.md)
- スキルの正本:
  [`/.rulesync/skills/`](../.rulesync/skills/)
- 創作技法テンプレートの正本:
  [`/_how_to.example/`](../_how_to.example/)

- [Contributing（docs への追記・修正ガイド）](contributing.md)
  docs/ に新しいページを追加・修正するときの記述ルール

## 読み進め方

1. 初めて触るときは [Getting Started](getting-started/index.md)
2. 画像生成や `.env` 設定を触るときは [Image Generation](image-generation/index.md)。漫画 IR のみなら [manga-prompt-ir](image-generation/manga-prompt-ir.md)、互換 Markdown の書式・タグ作業テンプレなら [manga-tag-generation](image-generation/manga-tag-generation.md)
3. 執筆フローや Mode を確認したいときは [Workflow](workflow/index.md)
4. リポジトリの規約や正本管理を確認したいときは [Project Structure](project-structure/index.md)
