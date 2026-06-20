# Workflow

Monogatari Coach を「どう動かすか」をユーザー視点で把握するためのページです。
まずは **指示文（コピペ）**で進められるページを起点にしてください。

## どちらのワークフローが合いますか？

制作を始める前に、どちらの進め方が合うかを確認してください。

| | 資料先出し | 対話先出し |
|---|---|---|
| **向いている人** | 設定・キャラを固めてから書きたい | 会話しながら形にしたい |
| **最初にやること** | 企画書・設計書・キャラ資料を作る | チャットモードで Phase 0 から始める |
| **本文は** | 資料が揃ってから `_novel_text/` へ | 会話ゲートを刻みながら `_novel_text/` へ |
| **参照するページ** | [指示出しベースのワークフロー](instruction-driven.md) | [チャットモード](chat-writing-mode.md) |

> **どちらでも途中から切り替えられます。** 資料先出しの途中でチャットモードに移ったり、その逆も可能です。

---

- **最重要**: [指示出しベースのワークフロー](instruction-driven.md)
- **詰まったとき**: [トラブルシューティング](troubleshooting.md) — 検証エラー・生成失敗・ファイルが見つからないときの次の一手
- **表層 UX・扱いやすさ（改善計画）**: [表層 UX 改善計画](surface-layer-ux.md) — 作品ステータス・名前付きレシピ（`workflows`）など、入口を薄くする設計
- **チャットモード（対話型・TRPG）**: [チャットモード](chat-writing-mode.md) — ゲートを刻みながら進める対話型執筆／TRPG セッション形式でパラメータを追跡しながら小説を作る
- **ユーザスキル（プラグイン相当）**: [ユーザスキルと雛形の置き場](user-skills.md) — `_how_to/skills/` に手書きスキルを置くときの正本／雛形／ツールパス（例: カクヨムルビ連携）
- **資料取り込み**: [Source Material Intake](source-material-intake.md)
- **企画・設計**: [Planning](planning.md)
- **評価（足切り・Editor Score・一貫性監査）**: [Reader Output](reader-output.md) — 下読み・足切り・Editor Score・Consistency Audit・Synopsis の保存先・操作ツール一覧
- **運用の骨格**: [自己発展型ルールガバナンス](self-evolving-governance.md)

運用上の正本（仕様・詳細）は [`/.rulesync/rules/overview.md`](../../.rulesync/rules/overview.md) です。

## ユーザー視点の流れ（何を指示するか）

1. **既存資料があるなら取り込む**
   - `source_material/` や `novels/_import/` を起点に「作品フォルダへ展開して」と指示する
2. **制作の設計（Plan）を固める**
   - `proposal.md` / `design_specification.md` / `character.md` / `world.md` などを作って、と指示する
3. **本文を書く（Writing）**
   - `_novel_text/novel_text*.md` に必ずファイル出力して、と指示する
4. **メタを残す（Meta）**
   - `_meta.md` を更新して進捗と引き継ぎを残して、と指示する
5. **必要になったら派生モードへ**
   - 画像タグ（Tag Mode）や漫画（Manga Tag Mode）を「必要になったタイミングで」指示する
   - Tag Mode で汎用 ID を省略させたくないときは **「Tag Mode（テンプレート一式）」**（正本: [concepts.md Tag Mode テンプレート一式](../../.rulesync/rules/concepts.md)）。作品固有の追加 ID は `_meta.md` の**キャラタグ方針・カスタム要素**に書く（指示例: [instruction-driven.md §G](instruction-driven.md#g-キャラクター画像タグを作るtag-mode)）
6. **品質を上げる**
   - 清書（文章校正）: `_novel_text_backup/` に旧版を退避してから `_novel_text/` を更新して、と指示する
   - 足切り（First Reader）: G1→G2→G3 の順で「第○章を足切り判定してください」と指示する
   - 完稿後の深掘り（Editor Score）: 足切り通過後に「Editor Score で採点してください」と指示する
   - 評価ツール: `novel_evaluation_prepare.py`（準備）・`novel_evaluation_diff.py`（推移表）・`novel_slush_gate_lint.py`（lint） — 詳細は [Reader Output](reader-output.md)

## Monogatari Coach の約束（ユーザー視点）

- **本文を会話だけで終わらせません。** Monogatari Coach は必ず `novels/.../_novel_text/novel_text*.md` に保存された状態を正とします。
- **執筆前にプロジェクトの不足がないか確認します。** 可能なら `tools/novel_project_check.py` で機械チェックします。
- **文字数の根拠を統一します。** 文字数は `tools/novel_char_count.py` の結果を正として扱います。
- **成果物の置き場所を混ぜません。** Tag / Manga / Meta は作品フォルダ内で分離して管理します。

## ユーザスキル（プラグイン相当）

公式の `.rulesync/skills/` とは別に、投稿変換や個人用の手順を **`_how_to/skills/<名前>/SKILL.md`** で持てます。雛形は **`_how_to.example/skills/`**、スクリプトは **`_how_to/tools/`** に置くのが既定です。概要・索引・具体例は **[ユーザスキルと雛形の置き場](user-skills.md)** を参照してください。

技術仕様の正本は [`.rulesync/rules/`](../../.rulesync/rules/) と [`.rulesync/skills/`](../../.rulesync/skills/) にあります。
