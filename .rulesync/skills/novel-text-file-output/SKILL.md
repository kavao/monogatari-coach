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

横断正本は **`.rulesync/rules/concepts.md`** の「完了扱い条件」。このスキルは、小説本文出力でその条件を満たすための実行手順を定める。創作技法契約の再読はスキル **`novel-planning`** の「執筆・清書での契約再読」に従う。

## 複数章の依頼でも1章ずつ直列に完了する

- ユーザーが1章だけを指定したときは、その章の**契約再読（事前）**・正本保存・確認・句読点・story reflectionまで完了して停止する。
- ユーザーが第X〜Y章の明示範囲、または複数章の列挙を指定したときは、チャット内の `batch_manifest` に順序を固定し、最初の未完了章から1章ずつ直列に処理する。各章の完了条件を満たしたら、確認を待たず `batch_manifest` の次章へ進み、範囲・列挙の終端で停止する。範囲外の章は開始しない。
- 各章の `target_manifest` はチャット内の一時メモとし、章番号、題名、本文パス、scene ID、設計アンカー、METRON / CHRONOS対象を列挙する。新しいリポジトリファイルや `context.md` の正本にはせず、分割本文・複数sceneは一覧の全対象が完了するまで章完了にしない。
- 明示範囲や列挙がない「次」は、対象作品の `_meta.md` の次回タスクと、本文として完了している最新章から次の未完了章を1章だけ解決する。チャットの記憶だけで決めず、前章が未完了のまま後続章を指定された場合は本文・prepareを始めず、前章の未完了理由を報告する。前章を飛ばすのはユーザーの明示指示がある場合だけとする。
- 章をまたぐ本文起草、候補受領、修復、publish、story reflectionの並列分担はしない。各章は `receive` → `inspect` →（必要なら修復）→ `publish` → story reflection の証跡を確認してから完了とし、`prepare` や run 内の `candidate.md` だけでは完了としない。ツール失敗、stale、`escalated`、ユーザーの停止指示では現在章を未完了としてバッチ全体を止め、後続章へ進まない。章ごとの完了は内部チェックポイントと査証ログへ残し、明示バッチの最終報告は終端後に行う。

### METRON / CHRONOS ON の章ゲート（単一章・複数章）

- 章の開始時に `novel_project_check --check-inspection-layers` を実行し、設定エラー（終了コード 1）なら本文作業を始めない。
- 単一章の依頼、`batch_manifest` の各章、既存章への場面追記のどれでも、開始時に対象場面を確定し、ON なら契約再読のあと `contract.yaml` / `beats.yaml` を整えてから `prepare` を実行し、active run を確認して本文作業へ進む。準備できない章はその章で停止し、`_novel_text` を直接追記・先行作成しない。単一章の停止条件はゲートの免除にならない。
- 章の遷移は `prepare` → 候補作成 → `receive` → `inspect`（必要なら修復・publish・story reflection）を同じ章で完了した証跡を条件にする。`novel_project_check --check-inspection-layers` の終了コードが0でも、未計測警告があれば次章へ進まない。
- 既存本文の後追い計測も同じゲートを使う。最初の未計測章を拾い、`contract/beats` の欠落を補ってから計測を完了し、次の章へ移る。

## 完了の定義（本文出力での適用）

ユーザーに「執筆した」「本文を出した」「ファイルに保存した」などと **完了扱い**で伝えてよいのは、`.rulesync/rules/concepts.md` の「完了扱い条件」を満たしたときに限る。本スキルでは次の順で適用する。経路が writing_bridge のときは、同じターンで `_novel_text` の手編集と `publish` を重ねない。

0. **創作技法契約（事前条件）**: 従来経路では起草の **前**、writing_bridge 経路では **`prepare` の前** に、スキル **`novel-planning`** の「執筆・清書での契約再読」を行う。完了報告に、使った selected 葉の拠り所を1句ずつ書く。契約外の how_to を創作判断に使ったままでは **未完了**（先に契約を更新するか、使わない）。Gate B 節が無い作品はカタログへ広がらず「契約なし」と書いてよい。旧形式のパス一覧は未変換のままでよく、索引以外の葉を再読する。
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
5. **報告の順序**: 上記 0〜4 の **後** に、**更新パス**と契約再読の要約を含めてユーザーへ報告する。確認・反映前に「保存した」「執筆を完了した」と述べ **ない**。
6. **次手（1行・実行しない）**: 完了報告の末尾に本文監査（Consistency Audit `text`）の指示文を1行出す。第1章の保存では `次手: 本文と設定の照合 → 「第1章の本文一貫性を監査して」`、第2章以降の保存では `次手: 本文の一貫性監査 → 「本文の一貫性を監査して」`。監査は自動で実行せず、執筆完了の条件にもしない。

**本文は提示層**（`concepts.md`「設計層と提示層」）。型名・ジャンル葉の名前・ID・カタログ短縮（葉のあだ名）や、「ここで第一の転換点が訪れ」のような設計上の位置の実況を本文に書かない。

## 執筆前の設計密度（分量は出来事の数で用意する）

章を書く前（writing_bridge 経路では `prepare` の前）に、対象章の目標字数と章出来事の件数を見る。基準は `_how_to.example/length_ops.md` §4.7。

1. **目標の取り先**: ユーザーが明示した字数か、`design_specification.md` の章の `**分量目安**：` の書き出しの字数だけ。どちらも無ければ密度は「保留」と報告して書き進めてよい。実測字数や場面の床を章の目標に読み替えない。
2. **判定**: `uv run python tools/design_density.py <作品フォルダ> --chapter N [--target N]`。1項あたり 500〜800字が推奨帯、1000字超は少なすぎ、300字未満は多すぎ。あわせて各項の親（目的・障害・結果・変化）が薄くないかを人が見る。本文が無い段階では字数の不足率を使わない。
3. **少なすぎ**: 本文を書かずに、足す子エピソードの案（「誰が何をした」の一文と、状態変化・持ち帰り・局所的効果）を出してユーザーの承認を待つ。承認されたら `design_specification.md` に項目を足し、同じ子エピソードを `_metron/<scene_id>/episodes.yaml` に `span_pending: true` で登録する（本文を書いたあと `span` の引用を補い、`span_pending` を外す）。CHRONOS ON なら当該場面の events を既存の承認手順で足し、METRON ON なら Beat と `chars_hint` を配り直してから書く。技法は `_how_to.example/episode/general/episode_sub_episode.md`。
4. **多すぎ**: 統合案だけを出して止まる。設計・本文・events を消すのは改稿工程と同じ承認のあと。
5. 依頼された章だけを判定し、既存作品の設計書を承認なしに増減しない。

## 起草の文型（言い換えで床を埋めない）

従来経路の起草、writing_bridge の `marked.md` / `candidate.md`、床不足の足し、`repair` の Deepen に共通する。完了条件にはしない。技法の詳細は `_how_to.example/rewrite.md`（短い文の連打、身体描写）を任意参照する。

- **禁止**: 直前の述語を次の主語にして意味を一周させる（「動く。動いた先に…近い。近いのは…」）。
- **禁止**: 「AでもBでもない」「〜だけだ」「〜というより」で、いまの行為や距離を説明し直す。
- **禁止**: 設計書のただし書き（何ではないか、どの呼称でもないか等）を地の文や Beat `intent` に写す。`intent` は動作だけにする。ただし書きは `contract.yaml` の forbidden へ置く。
- **不足時**: 出来事を増やさず、`character.md` の固定外見・身体から、今の距離で見える点を1つ足す。同一章で同じ点を説明し直さない。数値やカルテ語の連呼はしない。
- 読点をゲート回避のために地の文から抜かない。合否は句読点ゲートだけを正とする。
- **低品質文（スロップ）**: 起草の前に `_how_to.example/slop_patterns.md` を読み、意味破綻（物を主語にした取り違え、感覚・物理の不整合、比喩の対応崩れ）と定型句の重なりを書かない。保存前に、描写を足した文を同ファイル「出す前の検査」で一文ずつ読み直す（`concepts.md`「低品質文（スロップ）の回避」）。
- **作品固有の用語**: `world.md` の `## 用語` の正式名称か許容表記で書く。新しい名前、または名前のない新しい仕組み・規則・由来（〜できる／〜してはならない）が要るときは、本文に出す前に `## 用語（承認待ち）` へ登録案を書き、完了報告に足した語と理由を書く。用語集が無い作品ではこの時点で新しい書式の承認待ちの表を作り、旧形式の作品では新しい書式へ移すかを一度だけ作者に提案する（`_how_to.example/world_glossary.md` §2「既存の作品への適用」）。造語の多い作品を造語を作りやすいモデルで書いた作品の続きでは、書き始める前に用語照合を一言勧める（照合報告があり設定3点が変わっていなければ勧めない）。登録案の無い造語と設定に無い説明は書かない。既存の用語の物事を動作・感覚で細かく描くのは対象外。独自の語を初めて出すときは、その文か同じ場面の近くで意味が取れるように、定義の範囲の言い換えを添えるか動作・物で見せる。説明を次の章へ後回しにしない。用語集の定義に手順・条件がある語（技術・制度・現象）は、その手順・条件どおりに描き、台詞で条件と食い違うことを言わせない（`concepts.md`「作品固有の用語」、`_how_to.example/world_glossary.md` §3 の規則7）。

**禁止（幻覚完了の防止）**: 契約再読（事前）・正本更新・確認・句読点ゲート・ストーリー反映を満たす前に、執筆・保存の **完了**をユーザーに告げない。

**ツールでリポジトリに書けない環境**（ワークスペース非接続の対話のみ等）では、本文を提示し手動で `_novel_text` へ保存するよう依頼する。その場合、**当リポジトリ上の執筆完了とはみなさない**（「下書きを提示した」にとどめ、必要なら完了条件を明示する）。

## 追記・挿入・シーン追加

**初稿の新規執筆と同一の完了条件**とする。チャットに追加シーンや追記文だけを出し、**`novel_text*.md` を更新しなかった場合は未完了**（正本に反映されていない）。

- **対象ファイル**: 項分割（例: `novel_text03_1.md` と `novel_text03_2.md`）があるときは、作業開始時に **どのファイルへ書くか** を特定する。複数ファイルにまたがる加筆なら **ファイルごと**に書き込みと確認を行う。
- **確認**: **途中挿入**では「末尾だけ」の `Read` に頼らず、**追加した段落がファイル上に存在すること**を、挿入箇所の前後を含む `Read` で確認する。

## ツール予告と応答の継続（宣言のみで終えない）

「まず旧版を退避してから加筆します」「ツールで退避→加筆→確認を行います」など、**これからツールで実行する旨**を述べた場合、**その応答で前置きだけを出して終えない**。

明示範囲または複数章の列挙では、この実行継続を章ごとに繰り返し、各章の完了後に `batch_manifest` の次章へ自動遷移する。範囲・列挙の終端で停止し、失敗・stale・`escalated`・ユーザーの停止指示では後続章へ進まない。単一章の依頼では完了後に停止する。

- **同一応答（同一ターン）内**で、可能なら **退避・`_novel_text/` への書き込み・`Read`／`novel_char_count.py`** まで進める。長くなる場合でも、**最低でも退避（バックアップファイルの作成）または正本への書き込みのいずれか一歩**をツールで実行してから区切る。
- **応答が続く場合**、次のメッセージでは **同じ前置きを繰り返さず**、未完了ステップから **直ちにツール実行**で再開する。
- **例外（画像生成）**: **`tools/image_provider_generate.py`**・**`image_provider_novel_tag_batch.py`**・**`image_provider_novel_manga_batch.py`** 等は、上記「同一ターンで進める」の **対象外**。`.rulesync/rules/workflow-specification.md` の「画像生成: dry-run から本番まで」とスキル **`image-provider（旧 forge-txt2img）`** に従い、計画と `--dry-run` の提示までで一度止める。
- 旧版退避を含む清書・校正の手順はスキル **`novel-refinement-output`** に従う。

## 必須（執筆ターンごと）

上記 **「完了の定義（本文出力での適用）」** の手順に従う。経路は先に一つ選ぶ（下記「本文の書き方」）。

1. **契約再読（事前）**: スキル **`novel-planning`** の「執筆・清書での契約再読」。従来経路は起草前、writing_bridge は `prepare` 前。
2. **書き込み**: 従来経路では `novels/<novel_code>_<title>/_novel_text/novel_textXX.md`（項がある場合は `novel_textXX_Y.md`）を **新規作成・追記・置換**する。`publish` 経路では CLI が正本を書く。長文をチャットに貼るだけで終えない。
3. **確認**: **`Read`**（追記は末尾でよい／挿入は追加箇所の前後）または **`python tools/novel_char_count.py`** のいずれかで、保存内容・分量を検証する。
4. **句読点ゲート**: 従来経路は `python tools/novel_punctuation_metrics.py <対象ファイル> --gate`。`publish` 経路は先に `--dry-run` の予検を見て、本番後は `report.json` を確認する。失敗なら結合して書き直し（最大2回）。本文は戻さない。dry-run fail のときは正本を書かない。
5. **報告**: ユーザー向け返答に、**更新したファイルのパス**（リポジトリ相対でよい）と契約再読の要約を明示する。確認 **後** に完了を伝える。

## 本文の書き方（経路を一つにする）

完了条件（契約再読（事前）・正本更新・確認・句読点・ストーリー反映）は変えない。先に経路を一つ選ぶ。不変条件は **`.rulesync/rules/concepts.md`** の「執筆接続（writing_bridge）」。起動判定は **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」。

経路は次の順で決める。

1. METRON / CHRONOS が両方 OFF → 従来経路
2. 両方 ON → writing_bridge 経路（active run が無ければ `prepare` から）
3. 片方だけ ON（実効値の食い違い）→ 設定エラーとして報告し、本文作業を始めない
4. ユーザーが明示した CLI はフラグより優先する

### 従来経路（両方 OFF）

フラグが両方 OFF のときだけ使う。ON 作品で active run が無いことは、従来経路を選ぶ理由にならない。

1. スキル **`novel-planning`** の「執筆・清書での契約再読」を行う（起草前）。
2. `_novel_text` を直接更新する（本スキルの書き込み手順）。文型は上記「起草の文型」に従う。
3. 確認と句読点ゲートを本スキルどおり行う。
4. `novel-story-reflection` を行う。

### writing_bridge 経路（両方 ON）

新規場面・新規章・既存章への場面追記は、単一章でも複数章でも、対象場面にハッシュ一致の active run が無ければ **`prepare` を前条件**にする（手順は上記「章ゲート」）。active run は `_writing/<scene_id>/<run_id>/` にあり、`request.yaml` の本文ハッシュが今の `_novel_text` と一致するものを指す。ディレクトリがあるだけでは続きとみなさない。入口は `python tools/writing_bridge_cli.py`。同一ターンに `prepare` まで進めない場合は `_novel_text` を触らず、可能な成果物（contract / beats 等）だけを残して「未計測／要対応」と次回タスクを報告する。本文完了とは言わない。

**契約再読は `prepare` の前に行う**（スキル **`novel-planning`** の「執筆・清書での契約再読」）。active run の続きでも、そのターンでまだ再読していなければ `prepare` や起草の前に行う。

起草候補の raw hash と publish 後のマーカー除去・合成済み正本の raw hash は別版として扱う。完了照合は正本最終版と、それを指す publish / story reflection の記録で行い、候補版との raw hash 一致は要求しない。

- **起草**: 初稿は `context.md` の指示目標以上を1回で狙う（助言。検査床ではない）。文型は上記「起草の文型」に従う。起草ターンで字数合わせの反復計測をしない。CHRONOS 先行 publish からの METRON リテイクをしない。古い run の `instruction_chars` を現行倍率と見なさない。必要なら新 `prepare`。
- **候補の校正**: bridge経路では `receive` 前に候補へ `grammar --fix-dry-run` を行い、必要な機械修正も候補だけへ適用する。正本 `_novel_text` を直接校正しない。
- **検査**: `inspect`（必要なら先に `receive`）。CHRONOS ON は初回 inspect の前に observations を書く（未記録は exit 1）。引用座標は `locate-quote` で下書きし、一意一致だけ使う。重複は推測しない。候補や正本の版がずれたら `STALE_EVIDENCE`。同じ版へ `metron_cli.py analyze` / `chronos_cli.py check` を重ねない。`status` / `report.md` は required と advisory を分ける。`CHRONOS_NO_SCENE_EVENTS` は対象場面のイベント未登録を示す非ブロッキング警告で、`status` の `chronos_findings` と `report.md` の other で確認し、`success` をイベント検査済みと読まない。「保存へ」は床到達・必須なしに加え、C1 が success または skipped、repair が active でないときだけ。C1 未確認と修復中は案内しない。床到達・必須なしなら `repair-begin` しない。
- **修復**: 自動修復は床に対する不足率を `shortage_log.jsonl` に記録し、10% 以上なら `DESIGN_DENSITY` を notes に残すが止めない（完了報告で不足と設計追加の候補を伝える）。auto の Deepen も JOB ごとに著者へ承認を求めない（機械検査で採用し、保存前に主要な変化を1回報告する）。床に届いたあとの EndingRush は末尾を作り直さず、報告（`ENDING_RUSH_ADVISORY`）に残す。初回 inspect でシーン床到達かつ必須修復なしなら `repair-begin` しない。残る Beat hint / EndingRush は advisory のまま保存へ進む。床未達、必須修復残り、または `--intent explicit_deepen` のときだけ `repair-begin` / `repair-next` / `repair-submit`。`--scope beats` は指定 Beat だけを Deepen する（BeatMissing は範囲外でも必須）。生成打切りなど job を出せない必須は `repair-next` で `escalated` にし、新 `prepare` する。pending を捨てて止めるときは `repair-finish`。job JSON が消えていたら `STALE_EVIDENCE`。全文のやり直しは、begin 前なら同一 run の再 receive、begin 後なら新 `prepare`。`repair-next` / `repair-submit` の前後に receive・inspect を重ねない。この間は正本を触らない。`completed` / `escalated` のあと新しい稿は同じ run へ `receive` せず、新 `prepare` する。詳細は `_workingspace/plans/20260912_metron-ops-speed.md`。
- **正本反映**: `permissions.publish` がある run だけ `publish --dry-run` のあと `--authorization` 付きで `publish`。起草用 run に後から権限は付かない。ON の場面作業では、修復が terminal で床到達したら同じターンで `--allow-publish` の新 run へ進み、「保存しますか」と再確認しない。止めの明示があるときだけ止める。保存用は `--allow-publish` の新 run で `receive` する。未作成または空の正本は `request_kind=new` に selector を付けない。既存の非空本文だけ heading / scene アンカー / `append`（または `refine`）。見出し stub を先に正本へ置かない。`inspect --from-run` は CHRONOS ON かつ起草 run に observations があり本文 hash が一致するときだけ。欠落は UNKNOWN_REF。CHRONOS OFF は `--from-run` を付けない。CHRONOS ON では C1 成功前に正本を書かない。手編集で `_novel_text` を置換しない。`FINAL.md` だけでは完了にしない。`publish --dry-run` が句読点 fail なら本番 `publish` しない。
- **句読点**: `publish --dry-run` の予検は保存予定の対象ファイル全体。本番後の `report.json` も結合後全文。本スキルで `--gate` を重ねない。
- **ストーリー反映**: 正本が更新された直後に `novel-story-reflection`。
- **CHRONOS イベント（執筆後）**: 本文完了の条件にはしないが、報告は必須とする。publish とストーリー反映のあと、次を行う。
  1. 対象場面の `CHRONOS_NO_SCENE_EVENTS` を `report.json` で確かめる。
  2. イベントがある場面は、その結果（C1・`chronos_findings`）を報告する。同じ版へ `chronos_cli.py check` を重ねない。
  3. イベントが無い場面は、報告に「CHRONOS イベント未登録」と書き、`_meta.md` の次回タスクへ「第X章 scene_id のイベント登録」を**追記**する。ストーリー反映が書いた章の次回タスクは消さない。同じターンで当該場面のイベント YAML を手入力で草案化してよい（推奨）。その場合は `chronos_cli.py check` まで行い、結果を報告する。`extract_gate` 設定作品では、承認待ちの候補を用意してもよい（承認は作者）。
  4. `chronos_registered: success` や inspect の `success` を、イベント検査済みと読まない。

ユーザーが明示した CLI はフラグより優先し、個別 CLI は config.md を理由に拒否しない。

### 既稿の検査と後追い（ON 作品）

**既にある本文**の欠落表示と後追い計測に限る。新規場面の経路には使わない（新規は上記 writing_bridge 経路）。対象作品の config.md の「## 基本情報」表を共通パーサで読む。

1. 両方 OFF は、自動の init / analyze / 登録を行わない。
2. 未知値・重複キー・config.md の読込失敗・METRON / CHRONOS の食い違いは設定エラーとして報告し、検査手順を止める。既にある本文の完了は取り消さない。
3. METRON: 既稿の不足（contract / beats / run）と、計測後に本文が書き換わった章（「計測が古い」）を「未計測／要対応」として残す。`METRON_FROM` より前の章は下書き期として対象外。後追いは上記「章ゲート」と同じく、最初の未計測章で contract / beats を補ってから `prepare --allow-publish` → 現行本文を候補化 → `receive` → `inspect` → 必要なら修復 → `publish` する。マーカーを `_novel_text` に後付けしない。
4. CHRONOS: chronos/ が無ければ chronos_cli.py init を試み、既存のイベント YAML があれば chronos_cli.py check を実行する。イベントが無い章は「未登録」として次回タスクへ記録する。
5. 結果は本文保存と分けて報告し、成果物不足・CLI失敗・CHR001で既にある本文の完了を取り消さない。
6. **OFF で下書きした作品を ON にして洗練する**（明示 OFF した作品の経路）: 既稿から契約・Beat を起こすときは、章の出来事・結末・視点を変えない。指示目標は既稿の分量を基準にする（下回る候補にしない）。`publish` は既存の非空本文なので heading で当該章を置き換える。`publish` 後はストーリー反映を行う。CHRONOS のイベントは洗練する章から順に登録し、全章を一度に登録しない。手順の正本は `workflow-specification.md` フラグ節。

### 規定量調整（目標字数への伸縮）

ユーザーが既にある本文を目標字数へ合わせるよう指示したときに使う（例:「第3章を4000字に合わせて」）。新規場面の執筆と清書には使わない。原則は `concepts.md`「文章の伸縮」、技法の基準は `_how_to.example/length_ops.md`。

1. **範囲を決める**: 対象（Beat / 場面 / 章）、目標字数、許容帯（既定 ±3%）、試行回数の上限（既定3）を確かめる。ユーザーの字数は清書後の仕上がり目標とし、清書で削る分の余地（既定 +8%）を足した字数を増量の目標にする。余地はユーザーに尋ねず、最後の報告で説明する。床（場面の下限・Beat の下限）がある作品では、許容帯の上限が床を下回る指定を受け付けず、実効の下限は許容帯の下限と床の大きい方にする。現在の字数は `novel_char_count.py` で数える。
1a. **不足率を見る**: 増量の目標 `T`（余地込み）と同じ範囲の字数 `C` から `(T − C) ÷ T` を出す。10% 以上なら解像度展開を始めず、上記「執筆前の設計密度」の手順3と同じく子エピソードの追加を提案して承認を待つ（ON の `repair-begin --intent length` は `DESIGN_DENSITY` で止まり、`_metron/<scene_id>/shortage_log.jsonl` に記録する）。欠落 Beat があるときは止めずに先に埋める。
2. **既出事実リスト**: 調整前の本文を基準にする。時系列イベントを登録している場面では、エージェントがイベント一覧と本文の該当区間を照合する。著者には尋ねない。矛盾の疑いがあるときだけ、始めずに著者へ相談する。欠落 Beat があっても止めず、調整の中で先に埋める。
3. **一方向で伸縮する**: 増量は冗長化の除去 → 引き締め → 既出事実の範囲での解像度展開。減量は冗長化の除去 → 引き締め → 子エピソードの収束（持ち帰りのある要素は要約に残す）。往復しない。増量で上限を超えたら引き締めだけで戻す。
4. **候補の採用**: 増量と欠落 Beat の埋めは、機械検査を通れば採用する。JOB ごとに著者へ「採用／否認」を尋ねない（尋ねるのは作業の本体にならない範囲に限る）。引き締め・収束は、消えた・短くなった文を著者に示し、出来事・人物・所持品・情報の授受・関係・心境の変化・過去・因果の追加・変更・欠落が無いことの確認を得てから採用する。却下した候補も試行回数に数える。
4b. **続けて清書する**: 増量が終わったら、そのまま `rewrite.md` で清書する（スキル `novel-refinement-output` の手順5。METRON ON では作業稿へ行う）。床を割らないところで削るのをやめる（床はルールで厳守）。仕上がり目標との数%（5%以内）の差は誤差として合わせ直さず、増量へは戻らない。場面単位の反復（`--profile padding` の `padding_repeated_phrase`、または保存前の報告の反復語句の表）を先に見て、要所の1〜2回に絞る。
4a. **保存前の1回の確認**: 清書まで終わったら、主要な変化（字数の前後、採用した JOB、新しい文と消えた文、補助の印、イベント照合の根拠、場面契約の終了状態と次章の書き出し）を報告し、「この内容で保存してよいか」を1回だけ尋ねる。作業前と保存前の2回は尋ねない。気になる箇所を指摘されたら、その箇所だけを直してから保存する。
5. **止める**: 許容帯に入り床にも届いたら止める。上限回数に達した、または解像度展開・収束で届かないときは、不足・超過の字数と区間を報告して止める。増量で届かないときは、出来事を足す加筆工程（`_how_to.example/episode/general/episode_sub_episode.md`）を、減量で届かないときは出来事を削る改稿工程を提案し、ユーザー承認があるまで行わない。
6. **保存**: 経路は作品フラグで一つにする（清書の直接更新の例外には含めない）。
   - **両方 OFF**: 採用した本文は `_novel_text_backup/` へ旧版を退避してから正本を直接更新し、確認・ストーリー反映まで行う（`novel-refinement-output` の手順4・6〜9）。
   - **両方 ON**: 手順2〜5を writing_bridge の規定量調整で行う。`prepare --request-kind refine --selector-kind heading` の run で現行本文を `receive` → `inspect` →（イベントがある場面は）`canon-precheck` の材料をエージェントが照合し、`--result no_conflict --by agent --authorization "<照合の根拠>"` で記録 → `repair-begin --intent length --target-chars N`（`--tolerance` / `--length-scope beat --length-beat-id` / `--max-passes` は任意）→ `repair-next` → 候補作成 → `repair-submit --review confirmed`（増量と欠落 Beat の埋めは機械検査で採用。引き締め・収束は著者の確認を得て `--canon-authorization "<著者の確認の出典>"` を付ける）。`repair-begin` は `--finish-target N`（仕上がり目標。余地 +8% を自動で足す）を使う。`completed` のあと、出力された作業稿（`repair_state.json` の `output_path`。Beat マーカー付き）を写して清書し、`_metron/<scene_id>/refined.<run_id>.md` に置く（マーカーは消さない）。`repair-summary --refined <清書稿>` を著者に見せて1回だけ確認し、返答を `--accept --authorization` で記録する。この1回を保存の確認とし、保存用の `--allow-publish` 新 run へ清書稿を `receive` → `inspect` → `publish --dry-run` → `publish`（旧版退避は `publish` が行う）。`escalated` は手順5のとおり報告して止める。`_novel_text` を手編集しない。完了条件は上記「正本反映」と同じで、`publish` 後にストーリー反映を行う。
   - **食い違い**: 設定エラーとして報告し、調整を始めない。

METRON の規定量調整が行うのは、欠落 Beat の埋め（`regenerate`）と、出来事を変えない増量（`deepen`）・引き締め（`tighten`）・収束（`condense`）だけである。

- **契約修正**: 章末などを場面契約・設計に合わせて書き直すときは、規定量調整ではなく `repair-begin --intent contract_fix --scope beats --beat-ids ID --instruction "<直す内容>"` を使う。長さは旧稿ではなく Beat の床で判定し、同じ Beat に2回まで候補を出せる。契約を変える操作なので、採用には著者の確認を要する。

- **収束**: 引き締めで上限まで届かないとき、作者が `_metron/<scene_id>/episodes.yaml` に登録した子エピソード（`span` の開始・終了の引用で範囲を示す）だけを、持ち帰りも局所的効果も無い子 → 局所的効果だけの子 → 持ち帰りの軽い子の順に畳む。登録はエージェントが推測で作らず、作者と決める。
- **CANON 検査（任意）**: 候補ごとに `canon-check` で検査の指示を書き、別の呼び出しで JSON を得て `--result` と `--checker-model` で記録する。不合格の候補は、著者が確認しない限り採用しない。合格を著者確認の代わりにするのは、ユーザーが明示して `repair-begin --check-replaces-author` で始めたときだけ。開始前照合も `canon-precheck --check-prompt` → `--check-result` で検査に代えられる（同じオプトインが要る）。検査とその記録は、候補を作ったのと同じ呼び出しの自己申告で済ませない。
- **改稿工程**: 減量が届かず `LENGTH_ESCALATE_REVISE` で止まったら、出来事を削る候補ごとに `strip-check --episode-id`（または `--quote`）で参照を確かめる。終了コード 1（持ち帰り・他イベントの参照・後の本文の語）なら脱落せず収束に戻す。参照が無く、ユーザーが承認したときだけ `strip-record --reason --authorization` で記録し、本文は ON なら refine run の `publish`、OFF なら旧版退避のうえ直接更新で削る。CHRONOS イベントの削除・退避は CHRONOS の承認手順で行う。

## 試し書き・書き比べ（正本へ載せない）

「第N章を NAI で試し書きしてください」「第N章を local と NAI で書き比べてください」のように **試し書き / 書き比べ** と明示されたときだけ適用する。本文の完了条件（上記）は適用しない。正本・`_writing/`・`_metron/` は書かない。「NAI で執筆してください」（正本へ載せる本経路）とは別。

1. 対象場面の `_metron/<scene_id>/contract.yaml` / `beats.yaml` を確かめる（無ければ本経路と同じく親の LLM が起こす。Beat の割り方は親の LLM が決める）。
2. NAI を含むときは、設定の要点を親の LLM が `facts.yaml`（`canon_facts` と、Beat 別の `must_include` / `end_condition` の上書き）に書く。無いと NAI へ渡る要点が視点人物だけになる。
3. `tools/ai_writer_compare_cli.py plan <作品> --scene-id <id> --writers local,nai [--facts facts.yaml]`。表示された課金のある送信回数・モデル・保存先をユーザーに見せ、承認を得る（比較1回分をまとめて1回）。
4. 承認後に `run <run_dir> --writer nai --execute`。local は `context.md` を見てマーカー付き候補を1回で書き、`receive <run_dir> --candidate <path>` で渡す。
5. `measure <run_dir>` のあと、`review_skeleton.md` を元に `review.md`（総評・分量・項ごと・設定とのずれ・文体・採否）を書く。点数は付けない。
6. 完了報告に「正本は書いていない」と比較 run のパスを書く。正本にしたい候補があれば、本経路（起草 run → 保存用 run → `publish`）に載せる。

## 執筆モデルが Grok / xAI 系のとき

セッション先頭のモデル名、またはユーザーが Grok で書くと指定したときに適用する。他モデルは読み飛ばす。

- 従属節や読点の切れ目だけで「。」を打たない。「は、」「を、」の直後だけで文を切らない。
- 数値目標はここに書かない。合否は句読点ゲートだけを正とする。
- 造語や名前のない規則・由来の書き足し、登録語の定義のずれが出やすい。「起草の文型」の作品固有の用語の宣言を省かない。
- 独自の語を用語集に先に登録しても、本文やログラインで説明なしに並べやすい。独自の語の初出には、定義の範囲の言い換えを添える。ただし用語集の定義文を地の文へ写さない。視点人物がその場で見聞き・推測できる形で示し、視点人物が知りえない意味は聞き取った音・推測・謎として出す。一つの文に独自の語を三つ以上並べない。
- 仕事の動作や現象を一字の漢語や動詞から作った名詞に縮めやすい（「打が弱い」「白が残る」「端は、次だ」「届きではない」）。その語を述語と合わせてふつうの辞書の意味で読み、指す物事が取れなければ、普通の語に置き換える（「鐘を打つ力が弱い」「白い霧の帯が残る」。`world_glossary.md` §3 の規則6）。
- 自分で照合すると、一般の意味を持つ字（端）と動詞から作った名詞（届き）の略用を見落としやすい。用語照合は、書いたモデルとは別のモデル・別セッションに頼む（スキル `novel-evaluation-output`）。書き終えたら、承認待ちへ足した語に加え、癖を規則として言い切った箇所や、用語の定義から外れた使い方が無いかを読み直す。用語照合はほかのモデル・別セッションに頼むとよい（スキル `novel-evaluation-output`）。

## 従来経路での執筆直後の機械校正（推奨・任意）

上記 0〜5 で **執筆完了**としたあと、writing_bridge を使わない従来経路に限り、同一ターンまたは直後のターンで誤打・体裁の第一校正として次を実行する（詳細はスキル **`novel-text-rewrite-lint`**）。bridge経路の候補は、上記のとおり `receive` 前に校正する。publish後の正本へこの節の `--fix` を直接適用しない。後から正本を修正する場合は、新しい refine / publish run で再検査する。

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
- 従来経路での執筆直後の誤打・体裁の機械校正: **`novel-text-rewrite-lint`**（`grammar --fix`）。bridge候補は `receive` 前に校正する。
- **`rewrite.md` による清書・旧版退避と正本更新**: スキル **`novel-refinement-output`**
- 分量の公式カウント: **`novel-char-count`**（`tools/novel_char_count.py`）
- 句読点ゲート: **`tools/novel_punctuation_metrics.py --gate`**
- 画像生成の計画・承認・完了検証: **`image-provider（旧 forge-txt2img）`**
- 完了条件の横断正本: **`.rulesync/rules/concepts.md`**
- 執筆接続の起動判定: **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」
- プロジェクト全体の詳細仕様: **`.rulesync/rules/workflow-specification.md`** の Writing Mode と画像生成の事前確認
- 任意参照（完了条件ではない）: 場面密度・力みは `_how_to.example/episode/general/episode_reality.md`、失敗の許容は `episode_hindrance.md`
