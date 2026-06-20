# `_workingspace/diary/`

**横断ナレッジ日記**（作品をまたぐ方針・好み・ツール運用の決め事）を、**月次ファイル** `YYYYMM.md` に追記する場所です。

- **追記はツール経由**（エディタでの全文上書きは避ける）:
  `python tools/workspace_audit_log.py diary append "本文"`
- **体裁・使い分け**: スキル **`workspace-diary`**（`.rulesync/skills/workspace-diary/SKILL.md`）および `.rulesync/rules/overview.md` の「日記（横断ナレッジ）」節。
- 本 README だけリポジトリに含め、**月次 `*.md` は .gitignore で除外**しローカルに置く運用を推奨します（必要なら個別に追跡を外す）。月次本文は **`diary append`** で追加してください。
