# NovelAI Vibe / ポーション（横断・ユーザ既定）

**`_how_to/image_refs/novelai/`** に、複数作品で共通して使う NovelAI の Vibe Transfer 用ファイル（`.naiv4vibe` / `.naiv4vibebundle`）を置く。

- **正本（雛形の説明）**: この README（`_how_to.example/image_refs/novelai/README.md`）
- **作業コピー**: リポジトリ運用では **`_how_to/image_refs/novelai/`** に同内容の README と実ファイルを置く（`_how_to/*` は `.gitignore` 対象。バンドル本体はローカル正本）
- **作品固有**: `novels/<作品>/references/novelai/`（`novels/*` も Git 管理外）

`tools/fixtures/` は **JSON サンプル・手順用**であり、個人のポーションファイルの恒久置き場ではない。

---

## 現在のファイル（例）

| ファイル | 用途 | strength 目安 |
|----------|------|----------------|
| `2026-05-17_flat2.naiv4vibebundle` | **普段使い**（フラット／標準画風・既定） | 0.55〜0.65（soft 時は乗数 0.5） |

ファイル名は `YYYY-MM-DD_説明.naiv4vibebundle` のように日付＋用途で付けると、後から `_meta.md` と対応しやすい。

---

## 二層の使い分け

| 層 | パス | いつ使うか |
|----|------|------------|
| **横断既定** | `_how_to/image_refs/novelai/*.naiv4vibebundle` | 作品をまたいだ標準トーン |
| **作品ごと** | `novels/<code>_<title>/references/novelai/` | その作品だけ別画風・別 strength |

作品側の定量設定は **`novels/<作品>/_meta.yaml`** の `novelai.portions` に書く（雛形: `_how_to.example/_meta.yaml.example`）。バッチは **CLI 未指定時に自動読込**する。散文メモは `_meta.md` に残してよい。

---

## 優先順位（ポーション）

1. CLI `--novelai-reference-image-path`（複数可）
2. 作品 **`_meta.yaml`**（`portion_default` / `--novelai-portion-id`）
3. `.env` の `MONOCRI_MANGA_NOVELAI_REFERENCE_*`
4. なし

## `.env`（横断フォールバック）

作品に `_meta.yaml` が無いとき、リポジトリルートの `.env` で横断既定を入れられる（CLI・`_meta.yaml` が優先）。

```dotenv
MONOCRI_MANGA_NOVELAI_REFERENCE_IMAGE_PATHS=_how_to/image_refs/novelai/2026-05-17_flat2.naiv4vibebundle
MONOCRI_MANGA_NOVELAI_REFERENCE_STRENGTH=0.5
MONOCRI_MANGA_NOVELAI_REFERENCE_INFORMATION_EXTRACTED=0.5
```

複数ファイルは **セミコロン区切り**（例: `file1.naiv4vibebundle;file2.naiv4vibebundle`）。

---

## 漫画コマ生成（step1-panels）

背景資料と合成する前提では **`--omit-panel-background`** を併用する。

```powershell
# dry-run（_meta.yaml の portion_default を使う例）
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --input yaml --manga-stem manga_01 --source step1-panels `
  --omit-panel-background --color-mode full_color `
  --dry-run

# 別 ID のポーション
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --input yaml --manga-stem manga_01 --source step1-panels `
  --novelai-portion-id work_manga --dry-run

# CLI で上書き（最優先）
python tools/image_provider_novel_manga_batch.py novels/<作品> `
  --input yaml --manga-stem manga_01 --source step1-panels `
  --novelai-reference-image-path "_how_to/image_refs/novelai/2026-05-17_flat2.naiv4vibebundle" `
  --dry-run
```

単体確認は `tools/image_provider_generate.py` と `docs/image-generation/index.md` の「NovelAI Vibe Transfer」を参照。

### strength / IE（乗数）

バンドル内の `vibes[].importInfo`（NovelAI UI で保存した strength / IE）に、システム側の**乗数**を掛ける。比率は維持される。

| 乗数 | 効き |
|------|------|
| **1.0** | 既定・エクスポート値どおり |
| 0.5 前後 | 全体を薄める（0.22 → 0.11 など） |
| 1.2〜1.5 | 全体を強める（上限 1.0 でクリップ） |

`--novelai-reference-strength` / `_meta.yaml` の `strength` / `.env` の `MONOCRI_MANGA_NOVELAI_REFERENCE_STRENGTH` はいずれも乗数。

---

## 作品 `_meta.yaml` に書く例

`_how_to.example/_meta.yaml.example` を `novels/<作品>/_meta.yaml` にコピーし、`portions` を編集する。`_meta.md` には「`portion_default` は cross_flat」と散文メモだけ足してよい。

---

## 参照

- 操作・API パラメータ: `docs/image-generation/index.md`（NovelAI Vibe Transfer）
- 漫画バッチ: `tools/image_provider_novel_manga_batch.py`（`--novelai-reference-image-path`）
- 横断ルール: `.rulesync/rules/concepts.md`（画像生成）
