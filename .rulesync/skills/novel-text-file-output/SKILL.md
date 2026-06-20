---
name: novel-text-file-output
description: >-
  小説本文を会話にだけ書かず、novels/.../_novel_text/novel_text*.md へ必ず保存する。
  「執筆完了」の定義（ファイル更新＋確認）は本スキルで固定する。
  追記・シーン追加も新規執筆と同一の完了条件とする。
  執筆直後にファイル更新を Read または novel_char_count.py で確認する。
  「これからツールで退避／加筆／確認します」と述べたら宣言のみで終えず実行まで進める（実行継続）。
targets: ["*"]
---

## 目的

**本文の正本はリポジトリ上の Markdown ファイル**とする。モデルやクライアントによっては、**会話画面にだけ** 章本文を出し、**`_novel_text` を更新しない**ことがある（**Auto 以外・別 LLM 選択時**で起きやすい）。本スキルはその抜けを防ぐ。

横断正本は **`.rulesync/rules/concepts.md`** の「完了扱い条件」。このスキルは、小説本文出力でその条件を満たすための実行手順を定める。

## 完了の定義（本文出力での適用）

ユーザーに「執筆した」「本文を出した」「ファイルに保存した」などと **完了扱い**で伝えてよいのは、`.rulesync/rules/concepts.md` の「完了扱い条件」を満たしたときに限る。本スキルでは次の順で適用する。

1. **正本の更新**: `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）に、エージェントの **ファイル書き込み**（新規・追記・置換）が行われている。チャットへの貼り付けだけでは **完了ではない**。
2. **事実確認**（書き込み直後、いずれか必須）:
   - **`Read`** で当該 `novel_text*.md` を読み、内容が保存されていることを確認する。
   - または **`python tools/novel_char_count.py <対象ファイルまたは作品フォルダ>`** を実行し、分量を確認する。
3. **ストーリー反映**: スキル **`novel-story-reflection`** に従い、`_meta.md` の進捗・文字数・次回タスクを更新する。
4. **報告の順序**: 上記 1〜3 の **後** に、**更新パス**を含めてユーザーへ報告する。確認・反映前に「保存した」「執筆を完了した」と述べ **ない**。

**禁止（幻覚完了の防止）**: 正本更新・確認・ストーリー反映を満たす前に、執筆・保存の **完了**をユーザーに告げない。

**ツールでリポジトリに書けない環境**（ワークスペース非接続の対話のみ等）では、本文を提示し手動で `_novel_text` へ保存するよう依頼する。その場合、**当リポジトリ上の執筆完了とはみなさない**（「下書きを提示した」にとどめ、必要なら完了条件を明示する）。

## 追記・挿入・シーン追加

**初稿の新規執筆と同一の完了条件**とする。チャットに追加シーンや追記文だけを出し、**`novel_text*.md` を更新しなかった場合は未完了**（正本に反映されていない）。

- **対象ファイル**: 項分割（例: `novel_text03_1.md` と `novel_text03_2.md`）があるときは、作業開始時に **どのファイルへ書くか** を特定する。複数ファイルにまたがる加筆なら **ファイルごと**に書き込みと確認を行う。
- **確認**: **途中挿入**では「末尾だけ」の `Read` に頼らず、**追加した段落がファイル上に存在すること**を、挿入箇所の前後を含む `Read` で確認する。

## ツール予告と応答の継続（宣言のみで終えない）

「まず旧版を退避してから加筆します」「ツールで退避→加筆→確認を行います」など、**これからツールで実行する旨**を述べた場合、**その応答で前置きだけを出して終えない**。

- **同一応答（同一ターン）内**で、可能なら **退避・`_novel_text/` への書き込み・`Read`／`novel_char_count.py`** まで進める。長くなる場合でも、**最低でも退避（バックアップファイルの作成）または正本への書き込みのいずれか一歩**をツールで実行してから区切る。
- **応答が続く場合**、次のメッセージでは **同じ前置きを繰り返さず**、未完了ステップから **直ちにツール実行**で再開する。
- **例外（画像生成）**: **`tools/image_provider_generate.py`**・**`image_provider_novel_tag_batch.py`**・**`image_provider_novel_manga_batch.py`** 等は、上記「同一ターンで進める」の **対象外**。`.rulesync/rules/concepts.md` の「画像生成: dry-run から本番まで」とスキル **`image-provider（旧 forge-txt2img）`** に従い、計画と `--dry-run` の提示までで一度止める。
- 旧版退避を含む清書・校正の手順はスキル **`novel-refinement-output`** に従う。

## 必須（執筆ターンごと）

上記 **「執筆『完了』の定義（本文出力での適用）」** の手順に従う。

1. **書き込み**: `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）に対し、**新規作成・追記・置換**のいずれかで **必ずファイルを更新**する。長文をチャットに貼るだけで終えない。
2. **確認**: **`Read`**（追記は末尾でよい／挿入は追加箇所の前後）または **`python tools/novel_char_count.py`** のいずれかで、保存内容・分量を検証する。
3. **報告**: ユーザー向け返答に、**更新したファイルのパス**（リポジトリ相対でよい）を明示する。確認 **後** に完了を伝える。

## 執筆直後の機械校正（推奨・任意）

上記 1〜3 で **執筆完了**としたあと、同一ターンまたは直後のターンで、誤打・体裁の第一校正として次を実行する（詳細はスキル **`novel-text-rewrite-lint`**）。

```bash
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_textXX.md --profile grammar --fix-dry-run
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_textXX.md --profile grammar --fix
python tools/novel_text_rewrite_lint.py novels/NNN_作品名/_novel_text/novel_textXX.md --profile grammar
```

- **`--profile grammar` を付ける**（未指定の `default` では `　「`・半角 `,` 等は `--fix` 対象外）。
- 変更が多いときは **`_novel_text_backup/` へ `vNNN` 退避**してから `--fix`（`novel-refinement-output` の採番規則と同じ）。
- fix 後は **追加した段落付近を `Read`** し、意図しない置換がないか確認する。
- **`grammar --fix` だけでは「清書完了」と報告しない**（文学的な rewrite と `--strict` ゲートは別フェーズ）。

## 査証・メタ

- 進捗や文字数を **`_workingspace/log/`** や **`_meta.md`** に書くときは、**ファイルに存在する内容**に基づく（会話の記憶だけに頼らない）。
- 「執筆した」「◯文字」を査証ログに書く場合は、可能なら **`novel_char_count.py` の集計値**または **Read で読み取った事実**を根拠に含める。

## 関連

- 執筆**前**の資料・フォルダ: スキル **`novel-project-readiness`**（`tools/novel_project_check.py`）
- 執筆直後の誤打・体裁の機械校正: **`novel-text-rewrite-lint`**（`grammar --fix`）
- **`rewrite.md` による清書・旧版退避と正本更新**: スキル **`novel-refinement-output`**
- 分量の公式カウント: **`novel-char-count`**（`tools/novel_char_count.py`）
- 画像生成の計画・承認・完了検証: **`image-provider（旧 forge-txt2img）`**
- 完了条件の横断正本: **`.rulesync/rules/concepts.md`**
- プロジェクト全体のルール: **`.rulesync/rules/overview.md`** の「2.3 Writing Mode」「2.3.1 本文出力の確認」「2.2.1 画像生成（txt2img）の事前確認」
