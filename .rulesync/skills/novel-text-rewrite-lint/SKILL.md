---
name: novel-text-rewrite-lint
description: >-
  _novel_text/*.md の体裁規則（章番号・三点リーダー・セリフ句点・段落インデントなど）を
  tools/novel_text_rewrite_lint.py で機械チェックし、清書完了の判定を補助する。
  執筆直後は --profile grammar --fix で誤打の第一校正（rewrite の代わりにはしない）。
targets: ["*"]
---

## 目的

`_how_to/rewrite.md` の規則のうち**機械判定できる体裁**を自動検出し、清書後の取りこぼしを減らす。LLM が清書ターンの末尾で `--strict` を実行し、exit 0 を確認してから「清書完了」と報告する。

## 使用タイミング

| 場面 | コマンド | 期待 exit |
|------|----------|-----------|
| 執筆直後（誤打の機械校正） | `--profile grammar --fix`（前に `--fix-dry-run`） | 残り warning は人間／rewrite |
| 執筆直後（検出のみ） | `--profile grammar` | warning のみなら 0 |
| 清書前の総合チェック | `--profile full` | warning のみなら 0 |
| 清書完了ゲート | `--strict`（既定 `default`） | 0 でなければ未完了 |
| CI・`novel_project_check.py` 統合 | `--require-text-lint` | error または warning で 1 |

## 実行コマンド

```bash
# 作品フォルダ全体（_novel_text/*.md を一括）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名

# 清書完了ゲート（warning も失敗扱い）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --strict

# プロファイル指定
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --profile grammar
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --profile full

# 単一ファイル
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text01.md

# JSON 出力（CI・エージェント向け）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名 --json

# novel_project_check.py 経由（清書完了ゲートとして）
python tools/novel_project_check.py novels/NNN_作品名 --require-text-lint
python tools/novel_project_check.py novels/NNN_作品名 --require-text-lint --text-lint-profile full

# 執筆直後の機械校正（profile grammar 必須。未指定の default ではセリフ行頭・半角カンマ等は直らない）
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md --profile grammar --fix-dry-run
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_text03_2.md --profile grammar --fix
```

## 執筆直後の機械校正（`grammar --fix`）

**目的**: 執筆ターンで `_novel_text` に保存した直後、誤打・体裁の取りこぼしを **安全な置換だけ** 一括で直す。`_how_to/rewrite.md` の文学的な清書（主語・描写・文体）の **代わりにはしない**。

**執筆完了との関係**: スキル **`novel-text-file-output`** の「執筆完了」は **ファイル保存＋Read／`novel_char_count.py`** で判定する。`grammar --fix` はその **直後の推奨ステップ**であり、fix だけでは「清書完了」や「rewrite 済み」と報告しない。

### 推奨手順（章・項ファイル単位でも可）

1. 本文を `_novel_text/novel_text*.md` に保存し、**Read または `novel_char_count.py` で確認**（`novel-text-file-output`）。
2. **（推奨）** 対象ファイルを `_novel_text_backup/<元名>_vNNN.md` に退避（大量変更時。軽微なら `--fix-dry-run` の diff 確認でも可）。
3. `python tools/novel_text_rewrite_lint.py <対象> --profile grammar --fix-dry-run` で変更行数・内容を確認。
4. `python tools/novel_text_rewrite_lint.py <対象> --profile grammar --fix` を実行。
5. `python tools/novel_text_rewrite_lint.py <対象> --profile grammar` で残り warning を確認（句読点連続・空「」・助詞重複などは **自動修正されない**）。
6. **（別フェーズ）** `_how_to/rewrite.md` による清書 → `--profile full` → `--strict`（清書完了ゲート。下記）。

### `--fix` が直せるもの（grammar プロファイル時）

| rule_id | 置換内容 |
|---------|----------|
| `dialogue_leading_indent` | 行頭 `　「` / `　『` → `「` / `『` |
| `ascii_comma_in_prose` | 英数字直後以外の半角 `,` → `、` |
| `ellipsis_ascii` | `..` / `...` → `……` |
| `dialogue_trailing_period` | `。」` → `」` |
| `paragraph_indent` | 地の文行頭に全角スペース 1 字を付与 |

### `--fix` が直せないもの（検出のみ／人間・rewrite）

- `punctuation_consecutive`（`。。` `、、` 等）
- `empty_dialogue`（`「」`）
- `duplicate_particle`（`をを` 等）
- 章メタ（`default` / `full` の A ルール）
- セリフ**文中**の句点（`そうだね。教科書` 等。`。」` のみが `dialogue_trailing_period`）

### 注意

- **`--profile grammar` を必ず付ける**。`--fix` 単体（profile 未指定＝`default`）では、上表の多くは **実行されない**。
- `paragraph_indent` は行頭にスペースを **足す**。dry-run で意図しない行がないか確認する。
- `grammar --fix` 済みでも **清書完了** は `novel-refinement-output` ＋ `--strict`（既定 `default`）で別途確認する。

## プロファイル一覧

| profile | 有効ルール | 用途 |
|---------|-----------|------|
| `default`（未指定時） | A（章メタ）+ B（三点）+ C（セリフ句点） | 通常の清書後 lint |
| `grammar` | C（セリフ行頭インデント）+ D（段落インデント）+ E（句読点重複・空括弧・助詞・全角スペース） | 執筆直後の誤打・書きかけ検出 |
| `full` | default + grammar（A〜E 全部） | 清書前の総合チェック |
| `minimal` | B + C | 章メタ未整備の旧稿を体裁のみ確認 |
| `strict_all` | default + D（段落インデント） | 体裁総仕上げ |

## ルール一覧（主要）

### A. 章番号・前章メタ参照（rewrite §9）
- `chapter_meta_label`: `前章` `第X章` など（warning）
- `chapter_meta_compare`: `第X章と同じ` `前の章と同じ` など（warning）
- `author_meta`: `この章では` `プロットどおり` など（warning）

### B. 三点リーダー
- `ellipsis_ascii`: 半角 `...` や `..`（error）
- `ellipsis_wrong_unicode`: 単独 `…`（1個）を使っている（warning）— 正本形は `……`（U+2026×2）

### C. カギ括弧
- `dialogue_trailing_period`: 閉じ括弧直前の句点 `。」`（warning）
- `dialogue_leading_indent`: セリフ行頭の全角スペース `　「`（warning）— §1: `「`/`『` 行はインデント不要

### D. 段落インデント（stateful）
- `paragraph_indent`: 地の文行頭に全角スペースがない（warning）— §1: `「`/`『` 行・Markdown 非本文要素は除外

### E. 文法クイックチェック
- `punctuation_consecutive`: 句読点の連続 `。。` `、、`（error）
- `ascii_comma_in_prose`: 英数字以外の直後の半角 `,`（warning）— 例 `うん,そう` → `うん、そう`。`1,000` は除外
- `empty_dialogue`: 空のカギ括弧 `「」`（warning）
- `duplicate_particle`: 助詞の重複 `をを` `がが` `にに`（info）
- `fullwidth_space_double`: 全角スペース連続（info）

## YAML 設定（3層マージ）

ルールは以下の優先順で上書きマージされる。

```
_how_to.example/novel_text_rewrite_rules.yaml  ← 共有雛形（正本）
  ↓ _how_to/novel_text_rewrite_rules.yaml       ← プロジェクト横断の調整（任意）
    ↓ novels/<作品>/novel_text_rewrite_rules.yaml ← 作品別の allowlist 等（任意）
```

作品固有フレーズを allowlist に追加するときは、作品フォルダ直下に YAML を置く:

```yaml
# novels/069_…/novel_text_rewrite_rules.yaml
allowlist_patterns:
  - "二回目の◎"    # 物語内カウンタ（章番号ではない）
  - "三回目の"
```

## 清書完了の報告手順（rewrite 後）

執筆直後の `grammar --fix` とは **別フェーズ**。こちらが「清書完了」のゲート。

1. `_how_to/rewrite.md` に従いリライト。
2. `_novel_text_backup/` に旧版を退避（スキル **`novel-refinement-output`**）。
3. `python tools/novel_text_rewrite_lint.py novels/NNN --strict` を実行。
4. exit 0 を確認してから「清書完了」と報告する。
5. `_meta.md` の執筆フェーズ・ステータス欄に記録する:
   ```
   - **lint**: `--strict` で exit 0 確認済（YYYY-MM-DD、profile: full → strict）
   ```

exit 1 の場合は issues を修正してから再実行する。

## 関連スキル

- 執筆直後のファイル保存・完了判定: **`novel-text-file-output`**
- rewrite 清書・バックアップ: **`novel-refinement-output`**

## 正本

- ルール定義（YAML 雛形）: `_how_to.example/novel_text_rewrite_rules.yaml`
- ツール本体: `tools/novel_text_rewrite_lint.py`
- 清書技法: `_how_to/rewrite.md`（§1 体裁、§9 章番号・前章メタ参照の除去）
- 清書出力先: スキル **`novel-refinement-output`**
- 執筆前チェックへの統合: スキル **`novel-project-readiness`**（`--require-text-lint` オプション）
- 操作説明（詳細コマンド例）: `docs/tools/index.md` の「本文 rewrite lint」節
