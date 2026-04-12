# `_workingspace/log/`

**査証ログ**（セッションごとの作業の事実記録）を、**月次ファイル** `YYYYMM.md` に追記する場所です。

- **追記はツール経由**（エディタでの全文上書きは避ける）:  
  `python tools/workspace_audit_log.py append "本文"`
- **体裁・禁止事項**: スキル **`workspace-audit-log`**（`.rulesync/skills/workspace-audit-log/SKILL.md`）および `.rulesync/rules/overview.md` の「査証ログ」節。
- 本 README だけリポジトリに含め、**月次 `*.md` は .gitignore で除外**しローカルに置く運用を推奨します（必要なら個別に追跡を外す）。
