# `_how_to/` 領域の取り扱いガイド

`_how_to/` は「**準ルール・創作技法領域**」です。ツールの操作マニュアル（`docs/`）やLLMの行動規範（`.rulesync/`）とは性質が異なります。

---

## 何を入れる領域か

`_how_to/` には「**どう書くか・どう評価するか**」という**創作技法・作法・文法**を入れます。

| ファイル例 | 内容 |
|-----------|------|
| `novelcore.md` | 小説の文法・構成の一般原則 |
| `novel_structure.md` | 物語構造のパターン集 |
| `manga.md` | 漫画のコマ割り・演出の作法（ツールの検証・バッチ・export のコマンド詳細は [`docs/image-generation/manga-prompt-ir.md`](../image-generation/manga-prompt-ir.md)、互換 Step 長文テンプレは [`manga-tag-generation.md`](../image-generation/manga-tag-generation.md)） |
| `manga_tag.md` | 漫画タグ生成のルール・形式（英語タグ語彙・置き換え。Step1／`prompt_tags` 中心） |
| `manga_tag_step2.md` | Step2（ページ生成・`step2_summary`・抽象レイアウト）編集時の必読チェック（雛形: `_how_to.example/manga_tag_step2.md`） |
| `tag.md` | キャラクタータグ生成のルール |
| `rewrite.md` | 文章校正・清書の作法 |
| `reader.md` | 下読み・書評の評価観点 |
| `standard_reader.md` | 一般読者視点の興味判定軸 |
| `meta.md` | メタデータ管理のフォーマット |

**入れないもの**: ツールのコマンド・プロバイダ設定・環境変数などの運用情報（→ `docs/` へ）

---

## `docs/` との違い

| | `_how_to/` | `docs/` |
|--|-----------|---------|
| 性質 | 準ルール・創作技法 | 操作マニュアル |
| 例 | 漫画の演出作法、文章校正の手順 | コマンド例、.env設定方法 |
| 更新者 | **ユーザーが直接編集**する前提 | LLMが整備、ユーザーも参照 |
| LLMの扱い | 参照して執筆・評価を進める | 変更時に適宜更新する |

---

## 正本の管理（`_how_to/` と `_how_to.example/`）

```
_how_to.example/   ← 雛形・基準の正本（テンプレート）
_how_to/           ← ユーザーが作品・運用に合わせて調整する作業領域
```

- `_how_to.example/` は**変えたくない基準**を保持する。
- `_how_to/` はその場の判断で自由に調整してよい。
- `_how_to/` での変更を今後の基準として定着させたいときは、先に `_how_to.example/` を更新してからルール化する。

---

## LLMの取り扱いルール

- **LLMは `_how_to/` を参照して**、執筆・評価・タグ生成を進める。
- **LLMが `_how_to/` を書き換えるのは、ユーザーから明示的に依頼された場合のみ。**  
  技法・作法への提案はチャットで行い、記入するかどうかはユーザーが判断する。
- ツール運用の変更（プロバイダ追加・コマンド更新など）は `_how_to/` ではなく **`docs/`** へ反映する。

---

## `_how_to/tools/`（ユーザ用 Python）

**`_how_to/skills/`** のユーザスキルと一体で使う Python スクリプトは **`_how_to/tools/`** に置きます。リポジトリ全体の共有ツールは **`tools/`**（リポジトリ直下）です。

- 正本ルール: [`.rulesync/rules/concepts.md`](../../.rulesync/rules/concepts.md) の「共有ツールとユーザ用 Python」
- 入口と昇格の考え方: [`.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) の「`_how_to/tools/`（ユーザ用 Python）」
- 案内: [`_how_to/tools/README.md`](../../_how_to/tools/README.md)

短命の試行は **`tools_temp/`** を使います（`_how_to/tools/` は運用上そこそこ長く残すスクリプト向け）。

---

## `_how_to/skills/`（ユーザスキル）

**公式スキル（`.rulesync/skills/`）ではない**、手書きの手順置き場です。雛形は **`_how_to.example/skills/<名前>/`**、作業用にコピー・編集する先は **`_how_to/skills/<名前>/`** です。一覧は各 `skills/_index.md` から辿れます。

詳細・索引・具体例（カクヨムルビ連携など）は **[ユーザスキルと雛形の置き場](../workflow/user-skills.md)** を参照してください。

---

## `_index.md` で参照するファイルを管理する

`_how_to/_index.md` がこの領域の目次です。どのファイルをLLMが参照するかはこのファイルで制御できるため、**ユーザーが自由に編集・カスタムしてよい**。

使わないファイルはインデックスから外すだけで参照されなくなります。新しいファイルを追加したときは `_index.md` に行を追記してください。

---

## 参照先

- 正本の所在ルール: [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md)（「`_how_to/` と `docs/` の役割の違い」節）
- ユーザスキル（プラグイン相当）の全体像: [`/docs/workflow/user-skills.md`](../workflow/user-skills.md)
- 全体のプロジェクト構成: [`/docs/project-structure/index.md`](index.md)
