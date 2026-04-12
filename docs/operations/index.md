# Operations

日常運用や保守で迷いやすい事項をまとめます。

## rulesync

ルールやスキルの編集後は、生成物を直接いじらず `rulesync generate` を実行します。

```bash
rulesync generate
```

主編集先:

- `/.rulesync/**/*.md`
- `/.rulesync/skills/*/SKILL.md`
- `/.rulesync/mcp.json`
- `/.rulesync/hooks.json`

## 査証ログ

毎セッションの記録は `tools/workspace_audit_log.py` で追記します。

```bash
python tools/workspace_audit_log.py append "作業内容"
```

関連:

- [`/.rulesync/skills/workspace-audit-log/SKILL.md`](../../.rulesync/skills/workspace-audit-log/SKILL.md)
- [`/.rulesync/skills/workspace-diary/SKILL.md`](../../.rulesync/skills/workspace-diary/SKILL.md)

## ローカル試行

`tools_temp/` は試行錯誤用です。`tools/` の正規スクリプトを直接壊さないための避難場所として使います。

- 案内:
  [`/tools_temp/README.md`](../../tools_temp/README.md)

## 文字数と採番

- 文字数確認:
  [`/.rulesync/skills/novel-char-count/SKILL.md`](../../.rulesync/skills/novel-char-count/SKILL.md)
- novel_code 採番:
  [`/.rulesync/skills/novel-code-allocate/SKILL.md`](../../.rulesync/skills/novel-code-allocate/SKILL.md)
