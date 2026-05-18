# トラブルシューティング

このページでは、制作中によく起こる詰まりどころと、そのときの次の一手を説明します。

---

## IR 検証（`novel_prompt_ir_validate.py`）でエラーが出た

### 症状

```
python tools/novel_prompt_ir_validate.py novels/NNN_作品名
# → エラーメッセージが出て終了コード 1
```

### 次の一手

1. エラーメッセージに含まれる **ファイルパスと行番号**（または YAML キー名）を確認する
2. 該当の `manga/pages/manga_XX_pYY.yaml` または `tag/characters/<id>.yaml` を開いて修正する
3. 再度 `novel_prompt_ir_validate.py` を実行してエラーが消えることを確認する
4. 修正後に互換 Markdown が必要なら `novel_prompt_ir_export_md.py` を再実行する

### よくあるエラーの例

| エラーの内容 | 原因 | 修正方法 |
|---|---|---|
| `Field required` | 必須キーが抜けている | YAML に不足キーを追加する |
| `subjects must have at least 1` | コマの人物定義が空 | `subjects` にキャラを1件以上記述する |
| `background_concepts: 0 entries` | 背景資料が未定義 | `background_concepts` に1件以上追加する |
| `character not found` | `character_id` が `tag/characters/` に存在しない | YAML ファイル名と `character_id` を一致させる |

---

## `--dry-run` の件数・保存先が期待外れだった

### 症状

```
python tools/image_provider_novel_manga_batch.py novels/NNN_作品名 \
  --manga-stem manga_01 --source step1-panels --dry-run
# → 件数が少ない、または保存先が違う
```

### 次の一手

1. `python tools/novel_status.py novels/NNN_作品名` で `manga/pages/*.yaml` の件数を確認する
2. `--manga-stem` の指定（例: `manga_01`）が `manga/pages/manga_01_*.yaml` と一致しているか確認する
3. `_meta.yaml` に `workflows` を登録している場合は `--list-workflows` で内容を確認する
4. 問題が解決しない場合は、作品フォルダと `--manga-stem` の組み合わせをチャットで共有する

---

## 画像生成が HTTP 429 / 403 / 5xx で失敗した

### 症状

本番実行（`--dry-run` なし）中に API エラーが出て中断した。

### 次の一手

Monogatari Coach は自動的に別プロバイダへ切り替えません（意図しない課金・品質差を防ぐため）。

1. エラーの内容（HTTP コード・対象ジョブ・プロバイダ名）を確認する
2. 以下のいずれかの対応をチャットで指示する:
   - **待つ**: 429（レート制限）なら時間をおいて同じコマンドを再実行する
   - **プロバイダを変える**: `.env` の `IMAGE_PROVIDER` を変更してから再実行する
   - **件数を絞る**: `--manga-stem` や `--panel-ids` で対象を限定する
3. 再実行前に必ず `--dry-run` で確認してからユーザーが承認する

---

## 「完了」と表示されたがファイルが存在しない

### 症状

Monogatari Coach が「執筆完了」「エクスポートしました」「生成しました」と言ったが、ファイルが見当たらない。

### 次の一手

```bash
# 作品の状態を一覧で確認する
python tools/novel_status.py novels/NNN_作品名

# 本文ファイルを確認する
ls novels/NNN_作品名/_novel_text/

# 漫画画像を確認する
ls novels/NNN_作品名/manga/_assets/manga_01/comic/
```

状態を確認してからチャットで「ファイルが見当たりません」と伝えると、Monogatari Coach が再確認・再実行します。

---

## `_meta.md` と `_meta.yaml` のどちらを直せばよいか分からない

### 判断基準

| 直したい内容 | ファイル |
|---|---|
| 進捗・伏線・次のタスク・引き継ぎ情報 | `_meta.md` |
| 外部投稿用のあらすじ・キャッチコピー | `_meta.md` |
| NovelAI ポーション設定（パスや強度） | `_meta.yaml` |
| 名前付きレシピ（`workflows`） | `_meta.yaml` |
| §4/§5 のタグ層・TPO 表 | `_meta.md`（現行）または将来 `_meta.yaml` |

迷ったときはチャットに「`_meta.md` と `_meta.yaml` のどちらを直せばよいですか？」と聞いてください。

---

## 詰まりどころが上記にない場合

```
この問題が起きています: [症状を一言で]
作品フォルダ: novels/NNN_作品名
最後に実行したコマンド: [コマンドをコピー]
```

この形式でチャットに貼り付けると、Monogatari Coach が状態を確認してから対応します。
