# 表層 UX 改善計画

Monogatari Coach の**入口を薄くする**ための設計メモです。詳細コマンドは各リンク先を正とします。

## 目的

- 作品の進捗・次にやることを **1コマンド**で把握できるようにする
- 画像生成のフラグ組み立てを **名前付きレシピ**に集約する
- ルール・スキル・`docs/` の役割分担を保ちつつ、日常運用の認知負荷を下げる

## 現行の入口（実装済み）

### 作品ダッシュボード

[`novel_status.py`](../tools/index.md) の `--next` で、ファイルシステムの状態から次モード（Plan / Tag / Writing / 題字ロゴ / 出版 lock・proof 等）を1行表示します。`book.yaml` がある作品では、題字ロゴ不足・`cover.yaml` 未整備・lock 未作成・reader-proof 未生成を優先して案内します。

```bash
python tools/novel_status.py novels/NNN_作品名 --next
```

### 名前付きレシピ（`workflows`）

作品 `_meta.yaml` の `workflows` セクションにレシピを登録し、漫画バッチで `--workflow <id>` として呼び出します。詳細は [Image Generation — 名前付きレシピ](../image-generation/index.md#名前付きレシピworkflows) を参照してください。

```bash
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 --list-workflows
```

### 機械可読メタ（`_meta.yaml`）

画像生成向けのポーション・タグ前後挿入・`workflows` は `_meta.yaml` に記述します。読み込みは **`tools/novel_meta_yaml.py`（内部モジュール）** が担い、各バッチ・`novel_status.py` から import されます。ユーザーが直接叩く CLI ではありません。雛形は `_how_to.example/_meta.yaml.example` を参照してください。出版の完成目安は `_meta.md` §7（[表紙合成・題字ロゴ](cover-composition.md)）。

## 今後の改善候補（計画）

| 領域 | 案 | 状態 |
|------|-----|------|
| 出版・題字ヒント | `novel_status --next` が book.yaml / cover / lock / proof を見る | **実装済**（2026-07-26） |
| セッション再開 | `novel_status --next` の出力を `_meta.md` 次タスクと自動突合 | 検討中 |
| レシピ | `workflows` の dry-run 一覧を `novel_status` に統合表示 | 検討中 |
| ドキュメント | 指示出しテンプレと `docs/tools/index.md` の相互リンク強化 | 進行中 |

関連: [ワークフロー索引](index.md)、[指示出しベースのワークフロー](instruction-driven.md)、[トラブルシューティング](troubleshooting.md)