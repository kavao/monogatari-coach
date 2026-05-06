# docs/ への追記・修正ガイド

`docs/` に新しいページを追加したり、既存ページを修正したりするときの方針をまとめています。

詳細なルール（LLM が参照する正本）は [`.rulesync/rules/docs-writing.md`](../.rulesync/rules/docs-writing.md) にあります。

---

## このドキュメントは「人が操作するときの案内」です

`docs/` はシステムを使う人間向けの操作マニュアルです。以下はここには書きません。

- LLM への行動指示 → `.rulesync/` へ
- 創作技法・執筆作法 → `_how_to/` へ

---

## 5 つの記述ルール

### 1. 主語は「Monogatari Coach は」

「私は〜します」という表現は使いません。  
LLM の動作を説明するときは **「Monogatari Coach は〜します」** と書きます。

### 2. ページの冒頭に「目的」を書く

読者が最初の 1〜2 文で「これは自分に関係あるか」を判断できるようにします。

```
このガイドを読むと、画像生成プロバイダの切り替え方がわかります。
```

### 3. CLI コマンドは「目的 → dry-run → 本番 → 確認先」の順

コマンドの前に何をするコマンドかを一文で書き、`--dry-run` で確認してから本番実行する流れを体現します。実行後に「何が起きるか」も一言添えます。

```bash
# dry-run（確認）
python tools/image_provider_novel_manga_batch.py novels/051_作品名 \
  --manga-stem manga_01 --source step1-panels --dry-run

# 本番実行
python tools/image_provider_novel_manga_batch.py novels/051_作品名 \
  --manga-stem manga_01 --source step1-panels
```

実行後、`novels/051_作品名/manga/_assets/manga_01/` に画像が保存されます。

### 4. 内部動作は「ユーザーが見える視点」から説明する

「YAML IR を読み込んで〜」ではなく、「`manga/pages/*.yaml` を読んで、画像を `manga/_assets/` に保存します」のように、ユーザーが触るファイル・フォルダを起点に書きます。

処理の流れはこのように書きます。

```
ユーザーがコマンドを実行する
  → Monogatari Coach が manga/pages/*.yaml を読み込む
  → 画像生成 API にプロンプトを送る
  → novels/<作品>/manga/_assets/<manga_XX>/ に画像が保存される
```

### 5. 専門用語は初出時に一言説明する

YAML IR（キャラクター・漫画ページを構造化したデータファイル）、provider（画像生成 API の種類）、step1（コマ単位の生成指示）など、初めて出てくる用語には括弧で説明を入れます。

---

## 参照先

- ルール正本: [`.rulesync/rules/docs-writing.md`](../.rulesync/rules/docs-writing.md)
- ドキュメント全体の目次: [`docs/index.md`](index.md)
