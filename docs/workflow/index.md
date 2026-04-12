# Workflow

Monogatari Coach の制作フローを見渡すためのページです。ここは案内用で、運用上の正本は [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) です。

## モード一覧

1. Source Material Intake Mode
   `source_material/` や `novels/_import/` を展開して作品フォルダへ落とし込む
2. Reqruit Mode
   作家・読者・評価者などの役割を整える
3. Plan Mode
   企画、設計、Tag Mode、Manga Tag Mode を進める
4. Writing Mode
   本文を `_novel_text/` に出力する
5. Meta Management Mode
   `_meta.md` を更新して進捗と引き継ぎを残す
6. Writing Mode Refinement
   `_novel_text_re_/` に清書版を出力する
7. First Reader Mode / Interest Check Mode
   下読みと一般読者視点の評価を行う

## 重要な原則

- 会話だけに本文を書いて終えない
- 本文の正本は `novels/.../_novel_text/novel_text*.md`
- 執筆前は `tools/novel_project_check.py` による確認を推奨
- 文字数報告は `tools/novel_char_count.py` の結果を正とする
- Tag / Manga / Meta の関連ファイルは作品フォルダ内で分離管理する

## 詳細参照

- 全体ルール:
  [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md)
- 文字数:
  [`/.rulesync/skills/novel-char-count/SKILL.md`](../../.rulesync/skills/novel-char-count/SKILL.md)
- 画像レイアウト:
  [`/.rulesync/skills/novel-image-layout/SKILL.md`](../../.rulesync/skills/novel-image-layout/SKILL.md)
- 執筆前確認:
  [`/.rulesync/skills/novel-project-readiness/SKILL.md`](../../.rulesync/skills/novel-project-readiness/SKILL.md)
