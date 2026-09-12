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

ユーザーに「執筆した」「本文を出した」「ファイルに保存した」などと **完了扱い**で伝えてよいのは、`.rulesync/rules/concepts.md` の「完了扱い条件」を満たしたときに限る。本スキルでは次の順で適用する。経路が writing_bridge のときは、同じターンで `_novel_text` の手編集と `publish` を重ねない。

1. **正本の更新**: `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）が更新されている。更新手段は **従来のファイル書き込み** または **`writing_bridge_cli.py publish`** のいずれか一方。チャットへの貼り付けと `FINAL.md` だけでは **完了ではない**。
2. **事実確認**（書き込み直後、いずれか必須）:
   - **`Read`** で当該 `novel_text*.md` を読み、内容が保存されていることを確認する。
   - または **`python tools/novel_char_count.py <対象ファイルまたは作品フォルダ>`** を実行し、分量を確認する。
3. **句読点ゲート**（初稿・場面追記の本文ターン。誤打の `grammar --fix` だけなら不要）:
   - 従来経路: `python tools/novel_punctuation_metrics.py <対象ファイル> --gate`
   - `publish` 経路: 先に `publish --dry-run` の句読点予検を見る。fail なら正本を書かず結合して書き直す。本番後は `report.json` の句読点記録を正とする。同じターンで `--gate` を重ねない。
   - 終了コード 0 以外 / 記録が fail は **未完了**。本文は戻さない。短文を結合して書き直し、最大2回まで再実行する。
   - 数値の正はスクリプト側。スキルに閾値を写経しない。
4. **ストーリー反映**: スキル **`novel-story-reflection`** に従い、対象章を解決したうえで `_meta.md` の進捗・文字数・次回タスクと、`design_specification.md` の実文字数・状態および**確定出来事**を同期する。結果は `更新` / `差分なし` / `未完了`。解決不能と書込失敗は未完了として完了報告を止める。`publish` は `_meta.md` を書かない。
5. **報告の順序**: 上記 1〜4 の **後** に、**更新パス**を含めてユーザーへ報告する。確認・反映前に「保存した」「執筆を完了した」と述べ **ない**。

**禁止（幻覚完了の防止）**: 正本更新・確認・句読点ゲート・ストーリー反映を満たす前に、執筆・保存の **完了**をユーザーに告げない。

**ツールでリポジトリに書けない環境**（ワークスペース非接続の対話のみ等）では、本文を提示し手動で `_novel_text` へ保存するよう依頼する。その場合、**当リポジトリ上の執筆完了とはみなさない**（「下書きを提示した」にとどめ、必要なら完了条件を明示する）。

## 追記・挿入・シーン追加

**初稿の新規執筆と同一の完了条件**とする。チャットに追加シーンや追記文だけを出し、**`novel_text*.md` を更新しなかった場合は未完了**（正本に反映されていない）。

- **対象ファイル**: 項分割（例: `novel_text03_1.md` と `novel_text03_2.md`）があるときは、作業開始時に **どのファイルへ書くか** を特定する。複数ファイルにまたがる加筆なら **ファイルごと**に書き込みと確認を行う。
- **確認**: **途中挿入**では「末尾だけ」の `Read` に頼らず、**追加した段落がファイル上に存在すること**を、挿入箇所の前後を含む `Read` で確認する。

## ツール予告と応答の継続（宣言のみで終えない）

「まず旧版を退避してから加筆します」「ツールで退避→加筆→確認を行います」など、**これからツールで実行する旨**を述べた場合、**その応答で前置きだけを出して終えない**。

- **同一応答（同一ターン）内**で、可能なら **退避・`_novel_text/` への書き込み・`Read`／`novel_char_count.py`** まで進める。長くなる場合でも、**最低でも退避（バックアップファイルの作成）または正本への書き込みのいずれか一歩**をツールで実行してから区切る。
- **応答が続く場合**、次のメッセージでは **同じ前置きを繰り返さず**、未完了ステップから **直ちにツール実行**で再開する。
- **例外（画像生成）**: **`tools/image_provider_generate.py`**・**`image_provider_novel_tag_batch.py`**・**`image_provider_novel_manga_batch.py`** 等は、上記「同一ターンで進める」の **対象外**。`.rulesync/rules/workflow-specification.md` の「画像生成: dry-run から本番まで」とスキル **`image-provider（旧 forge-txt2img）`** に従い、計画と `--dry-run` の提示までで一度止める。
- 旧版退避を含む清書・校正の手順はスキル **`novel-refinement-output`** に従う。

## 必須（執筆ターンごと）

上記 **「完了の定義（本文出力での適用）」** の手順に従う。経路は先に一つ選ぶ（下記「本文の書き方」）。

1. **書き込み**: 従来経路では `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）を **新規作成・追記・置換**する。`publish` 経路では CLI が正本を書く。長文をチャットに貼るだけで終えない。
2. **確認**: **`Read`**（追記は末尾でよい／挿入は追加箇所の前後）または **`python tools/novel_char_count.py`** のいずれかで、保存内容・分量を検証する。
3. **句読点ゲート**: 従来経路は `python tools/novel_punctuation_metrics.py <対象ファイル> --gate`。`publish` 経路は先に `--dry-run` の予検を見て、本番後は `report.json` を確認する。失敗なら結合して書き直し（最大2回）。本文は戻さない。dry-run fail のときは正本を書かない。
4. **報告**: ユーザー向け返答に、**更新したファイルのパス**（リポジトリ相対でよい）を明示する。確認 **後** に完了を伝える。

## 本文の書き方（経路を一つにする）

完了条件（正本更新・確認・句読点・ストーリー反映）は変えない。先に経路を一つ選ぶ。不変条件は **`.rulesync/rules/concepts.md`** の「執筆接続（writing_bridge）」。起動判定は **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」。

### 従来経路（既定）

フラグが両方 OFF、または ON でも対象場面にハッシュ一致の active run が無いとき。

1. `_novel_text` を直接更新する（本スキルの書き込み手順）。
2. 確認と句読点ゲートを本スキルどおり行う。
3. `novel-story-reflection` を行う。
4. フラグ ON で run が無いときだけ、下記「従来の検査」を起動する。

### writing_bridge 経路

対象場面に `_writing/<scene_id>/<run_id>/` の active run があり、`request.yaml` の本文ハッシュが今の `_novel_text` と一致するとき。入口は `python tools/writing_bridge_cli.py`。ディレクトリがあるだけでは切り替えない。`prepare` 前は従来経路。

- **起草**: 初稿は `context.md` の指示目標以上を1回で狙う（助言。検査床ではない）。起草ターンで字数合わせの反復計測をしない。CHRONOS 先行 publish からの METRON リテイクをしない。古い run の `instruction_chars` を現行倍率と見なさない。必要なら新 `prepare`。
- **検査**: `inspect`（必要なら先に `receive`）。CHRONOS ON は初回 inspect の前に observations を書く（未記録は exit 1）。引用座標は `locate-quote` で下書きし、一意一致だけ使う。重複は推測しない。候補や正本の版がずれたら `STALE_EVIDENCE`。同じ版へ `metron_cli.py analyze` / `chronos_cli.py check` を重ねない。`status` / `report.md` は required と advisory を分ける。「保存へ」は床到達・必須なしに加え、C1 が success または skipped、repair が active でないときだけ。C1 未確認と修復中は案内しない。床到達・必須なしなら `repair-begin` しない。
- **修復**: 初回 inspect でシーン床到達かつ必須修復なしなら `repair-begin` しない。残る Beat hint / EndingRush は advisory のまま保存へ進む。床未達、必須修復残り、または `--intent explicit_deepen` のときだけ `repair-begin` / `repair-next` / `repair-submit`。`--scope beats` は指定 Beat だけを Deepen する（BeatMissing は範囲外でも必須）。生成打切りなど job を出せない必須は `repair-next` で `escalated` にし、新 `prepare` する。pending を捨てて止めるときは `repair-finish`。job JSON が消えていたら `STALE_EVIDENCE`。全文のやり直しは、begin 前なら同一 run の再 receive、begin 後なら新 `prepare`。`repair-next` / `repair-submit` の前後に receive・inspect を重ねない。この間は正本を触らない。`completed` / `escalated` のあと新しい稿は同じ run へ `receive` せず、新 `prepare` する。詳細は `_workingspace/plans/20260912_metron-ops-speed.md`。
- **正本反映**: `permissions.publish` がある run だけ `publish --dry-run` のあと `--authorization` 付きで `publish`。起草用 run に後から権限は付かない。METRON ON の場面作業では、修復が terminal で床到達したら同じターンで `--allow-publish` の新 run へ進み、「保存しますか」と再確認しない。止めの明示があるときだけ止める。CHRONOS ON だけでは進めない。保存用は `--allow-publish` の新 run で `receive` する。未作成または空の正本は `request_kind=new` に selector を付けない。既存の非空本文だけ heading / scene アンカー / `append`（または `refine`）。見出し stub を先に正本へ置かない。`inspect --from-run` は CHRONOS ON かつ起草 run に observations があり本文 hash が一致するときだけ。欠落は UNKNOWN_REF。CHRONOS OFF は `--from-run` を付けない。CHRONOS ON では C1 成功前に正本を書かない。手編集で `_novel_text` を置換しない。`FINAL.md` だけでは完了にしない。`publish --dry-run` が句読点 fail なら本番 `publish` しない。
- **句読点**: `publish --dry-run` の予検は保存予定の対象ファイル全体。本番後の `report.json` も結合後全文。本スキルで `--gate` を重ねない。
- **ストーリー反映**: 正本が更新された直後に `novel-story-reflection`。

ユーザーが明示した CLI はフラグより優先し、個別 CLI は config.md を理由に拒否しない。

### 従来の検査（run が無い ON 作品）

本文の完了条件は変えない。本文保存・確認・句読点ゲート・ストーリー反映のあと、対象作品の config.md の「## 基本情報」表を共通パーサで読む。

1. 行なしまたは OFF は、自動の init / analyze / 登録を行わない。
2. 未知値・重複キー・config.md の読込失敗は設定エラーとして報告し、検査手順を止める。本文完了は取り消さない。
3. METRON: ON は、既稿の不足を「未計測／要対応」として残し、新規章では可能なら contract / beats / マーカー付き draft を用意して analyze する。同一ターンに用意できない場合は `_novel_text` を触らず、可能な成果物だけを残して「未計測／要対応」と次回タスクを報告する。マーカーを _novel_text に後付けしない。
4. CHRONOS: ON は、chronos/ が無ければ chronos_cli.py init を試み、既存のイベント YAML があれば chronos_cli.py check を実行する。当該章のイベント手入力は推奨であり、必須の完了条件にはしない。
5. METRON / CHRONOS の結果は本文保存と分けて報告し、成果物不足・CLI失敗・CHR001で本文完了を取り消さない。未作成の scene / 未登録イベントは次回タスクへ記録する。

## 執筆モデルが Grok / xAI 系のとき

セッション先頭のモデル名、またはユーザーが Grok で書くと指定したときに適用する。他モデルは読み飛ばす。

- 従属節や読点の切れ目だけで「。」を打たない。「は、」「を、」の直後だけで文を切らない。
- 数値目標はここに書かない。合否は句読点ゲートだけを正とする。

## 執筆直後の機械校正（推奨・任意）

上記 1〜4 で **執筆完了**としたあと、同一ターンまたは直後のターンで、誤打・体裁の第一校正として次を実行する（詳細はスキル **`novel-text-rewrite-lint`**）。

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
- 対象作品の `config.md` に `AUDIT_LOG | OFF` があるときは査証ログを追記しない。

## 関連

- 執筆**前**の資料・フォルダ: スキル **`novel-project-readiness`**（`tools/novel_project_check.py`）
- 執筆直後の誤打・体裁の機械校正: **`novel-text-rewrite-lint`**（`grammar --fix`）
- **`rewrite.md` による清書・旧版退避と正本更新**: スキル **`novel-refinement-output`**
- 分量の公式カウント: **`novel-char-count`**（`tools/novel_char_count.py`）
- 句読点ゲート: **`tools/novel_punctuation_metrics.py --gate`**
- 画像生成の計画・承認・完了検証: **`image-provider（旧 forge-txt2img）`**
- 完了条件の横断正本: **`.rulesync/rules/concepts.md`**
- 執筆接続の起動判定: **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」
- プロジェクト全体の詳細仕様: **`.rulesync/rules/workflow-specification.md`** の Writing Mode と画像生成の事前確認
- 任意参照（完了条件ではない）: 場面密度・力みは `_how_to.example/episode/general/episode_reality.md`、失敗の許容は `episode_hindrance.md`
