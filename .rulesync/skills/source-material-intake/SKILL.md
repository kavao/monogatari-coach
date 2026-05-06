---
name: source-material-intake
description: >-
  source_material/ や novels/_import/ の原資料を読み、Monogatari Coach の
  novels/<code>_<title>/ 形式へ展開する。資料の保全、同一作品の判定、
  novel_code 採番、_source_material 退避、必要ファイル生成の手順を固定する。
targets: ["*"]
---

## 目的

既存の原資料を、勢いを失わせずに Monogatari Coach の作品フォルダへ展開する。

このスキルは **資料取り込み・資料展開** の実行手順を定める。採番は **`novel-code-allocate`**、執筆前の揃い確認は **`novel-project-readiness`** を併用する。

## 発動条件

次のいずれかに当てはまるときに使う。

- ユーザーが「この資料を元に落とし込んで」「source_material を使って」「元資料を使って」などと指示した。
- リポジトリ直下に `source_material/` がある。
- `novels/_import/` に取り込み対象の資料群がある。

## 最初に判断すること

1. **同一作品の有無**: 既存の `novels/` に同一作品らしいフォルダがあるか確認する。
2. **新規か更新か**: 既存作品があればバックアップや差分更新を優先し、無ければ新規作品として展開する。
3. **作品分割**: 複数作品が混在する場合は、サブフォルダ単位を1作品候補とみなし、作品分割案を作る。
4. **質問の最小化**: 判断が割れるときだけ、1〜3個の短い質問をする。

## 取り込み手順

1. **資料の全量把握**
   - `source_material/` または `novels/_import/` 配下のファイル・フォルダを読む。
   - 確定情報、候補、メモ、本文下書きを分ける。
2. **Monogatari Coach 形式へ対応付け**
   - 作品名／ログライン／あらすじ → `proposal.md`
   - テーマ／コンセプト／章構成／相関図 → `design_specification.md`
   - 世界設定／用語／地理／歴史 → `world.md`
   - 登場人物表／口調／背景／課題 → `character.md`
   - 本文・下書き・シーン案 → `_novel_text/novel_textXX.md`
3. **novel_code の採番**
   - 新規作品では `tools/novel_code_allocate.py` を実行し、次の番号候補を確認する。
   - 資料上の作品名が揺れる場合は、`config.md` に「資料上の別名」を残す。
4. **作品フォルダへ展開**
   - `novels/<novel_code>_<novel_title>/` を作成、または既存作品を更新する。
   - `proposal.md`, `design_specification.md`, `config.md`, `character.md`, `world.md`, `_meta.md`, `_novel_text/`, `_reader/` を揃える。
5. **原資料の保全**
   - 原資料は改変しない。
   - 必要に応じて作品フォルダ内の `_source_material/` に参照用として退避する。
   - 以後の改稿・執筆では、展開済みの `novels/<作品>/` を正とする。
6. **検証**
   - `tools/novel_code_allocate.py verify novels/<作品>` で `config.md` とフォルダ名を確認する。
   - `tools/novel_project_check.py novels/<作品>` で執筆前の必須ファイル・ディレクトリを確認する。

## 禁止・注意

- 原資料を直接改変して、展開済みファイルの代わりにしない。
- 同一作品があるのに、確認なしで別番号の新規作品として重複作成しない。
- 互いに別作品の資料を1作品へ無理に混ぜない。
- 判断が割れる場合は、作品分割案を示してから最小限の質問をする。

## 関連

- 採番: `.rulesync/skills/novel-code-allocate/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- 本文保存: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 操作説明: `docs/workflow/source-material-intake.md`
