---
name: novel-project-readiness
description: >-
  執筆開始前に、作品フォルダの必須資料（proposal 等）・必須ディレクトリ
  （_novel_text, _reader）・config とフォルダ名の整合を tools/novel_project_check.py で検証する。
targets: ["*"]
---

## 目的

**本文を書き始める前**に、Monogatari Coach 想定の **資料・フォルダが揃っているか** を曖昧にせず確認する。エージェントは Writing Mode に入る直前、またはユーザーが「執筆して」と言った直後に本スキルに従い **機械チェック**する。

## 必須（機械検証）

リポジトリルートで、対象作品フォルダを渡す:

```bash
# 基本チェック（character.md 構造 lint 含む・既定）
python tools/novel_project_check.py novels/NNN_作品タイトル

# 画像保存フォルダも含めた完全チェック（推奨）
python tools/novel_project_check.py novels/NNN_作品タイトル --check-image-layout --require-tag

# character.md 構造 lint をスキップする場合
python tools/novel_project_check.py novels/NNN_作品タイトル --no-character-structure
```

**改善内容（今後の運用）**:
- **既定で `character.md` 構造 lint**（`plan` profile）。無効化は `--no-character-structure`
- `--check-image-layout`: `novel_image_layout.py` と連携し、`tag/<romaji>/` と `manga/_assets/` の完全性を検証
- 出力が明確化（「=== 結果: OK ===」と「次にすべきことリスト」を自動表示）
- Windows コンソールの文字化け対策（`stdout.reconfigure(utf-8)`）
- 不足項目が一目でわかり、次に何をすべきかが明確に表示される

**使用タイミング**: Writing Mode に入る直前、またはユーザーが「執筆して」と言った直後。終了コード **0** を確認してから本文執筆に入る。

- **必須ファイル**（いずれも一定バイト数以上）: `proposal.md`, `design_specification.md`, `config.md`, `character.md`, `world.md`, `_meta.md`, `_meta.yaml`
- **必須ディレクトリ**（空でよい）: `_novel_text/`, `_reader/`
- **config / フォルダ名**: `tools/novel_code_allocate.py verify` と同じ整合（`novel_ID` 表とフォルダ先頭番号）

終了コード **0** なら「執筆前の必須は満たす」。**1** なら欠けを修正してから執筆する。

### オプション

| フラグ | 意味 |
|--------|------|
| `--require-tag` | `tag/*.md` が1件以上あることを必須（Tag Mode 済みを求めるとき） |
| `--require-manga-dir` | `manga/` があることを必須 |
| `--min-file-bytes N` | 空ファイル除けのしきい値（既定 48） |
| `--json` | CI やエージェント向け JSON 出力 |
| `--bootstrap` | `_meta.yaml` / `_novel_text/` / `_reader/` / `references/novelai/` を不足分だけ作成してからチェック |
| `--no-character-structure` | `character.md` 構造 lint をスキップ（**既定は実行**） |
| `--require-character-structure` | 構造 lint を明示的に有効化（既定と同じ。後方互換用） |
| `--character-profile NAME` | `character.md` 構造 lint の profile（既定 `plan`） |
| `--character-strict` | 表形式などの移行猶予 WARN を ERROR 扱いにする |
| `--character-suggest` | `--json` 出力に不足項目追記案・表形式変換案を含める |
| `--check-inspection-layers` | `config.md` の METRON / CHRONOS / AUDIT_LOG フラグと保存先を確認（WARN は終了コード 0） |

## 不足時の典型対処

- **`_novel_text/` または `_reader/` が無い**: ディレクトリを作成（空でよい。Git 用に `.gitkeep` を置いてもよい）。
- **`tag/<romaji>/` 未作成の WARN**: スキル **`novel-image-layout`**（`tools/novel_image_layout.py scaffold`）で作成。
- **採番 NG**: スキル **`novel-code-allocate`** に従い `config.md` の `| novel_ID |` 表とフォルダ名を揃える。
- **character.md 構造 NG**: スキル **`novel-character-profile`** に従い、必須ラベルの追加や表形式から `- **ラベル**:` 形式への移行を行う。

## 正本

- ファイル一覧の意味付け: **`.rulesync/rules/workflow-specification.md`** の「小説ファイル (novels/[novel_code]_[novel_title]/)」
- 人物プロフィールの構造 lint: スキル **`novel-character-profile`**
- 本文保存の確認: スキル **`novel-text-file-output`**
- 検査フラグ: `--check-inspection-layers`。METRON / CHRONOS ON の執筆接続は **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」
