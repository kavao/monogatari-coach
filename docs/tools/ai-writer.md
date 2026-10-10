# AI 執筆基盤（NovelAI テキスト生成）

**TL;DR**: NovelAI のテキストモデル（GLM-4.6 と Xialong）で小説本文の続き・指定つきの続き・挿入を生成し、生成結果を「候補」として保存する仕組みです。生成した文は作品の本文（`_novel_text/`）へ自動では書き込みません。現在は Phase 1（試作段階）で、主に確認用のコマンドから使います。

設計と進み具合の正本は、作業計画 `_workingspace/plans/20261008_novelai_novel.md` です（`_workingspace/` はローカルの作業領域で、リポジトリには含まれません）。

---

## このドキュメントを使う場面

### どんな場面で使うか

- NovelAI のテキスト生成がつながるか確かめたいとき
- 「続きを書く」「契約（目的・含めるもの・終わる位置）を指定して続きを書く」「文と文の間に描写を挟む」の 3 つの操作を試したいとき
- 生成の品質をまとめて比べたいとき（日本語 Benchmark、字数の比較実験）
- 同じ場面から「この先どうなるか」の別案をいくつか見比べ、気に入った展開や表現を拾いたいとき（別の展開を見る、試作）

前提として、`.env` に `NOVELAI_ACCESS_TOKEN` が設定されている必要があります。テキスト生成は NovelAI の契約の範囲で使えます（Xialong は Opus 契約が必要です）。

### チャットへの指示文

この機能はまだスキルとして登録されていません。チャットで次のように依頼します。

```text
NovelAI の接続を確認して
```

と入力すると、Monogatari Coach は送信内容を dry-run（送らずに内容だけを表示する確認）で示し、承認を求めます。「承認します」と返すと送信します。

ほかの例:

```text
AI 執筆基盤で daily の場面の 3 操作を試して
日本語 Benchmark を dry-run して
romance の場面で、Xialong で別の展開を 3 案見たい
```

### Monogatari Coach が行うこと

1. 実行するコマンドを決め、dry-run で送信内容（モデル・送り先・本文・出力上限）を表示します。トークンは `Bearer ***` と伏せます。
2. ユーザーの承認を待ちます。NovelAI への送信は契約の利用枠を使うため、承認なしには送りません。
3. 承認後に送信します。同時に生成できるのは 1 アカウント 1 本なので、1 本ずつ順番に送ります。
4. 結果を `_workingspace/ai_writer/` 以下に保存し、要点をチャットで報告します。

### ユーザーが確認できるもの

- コンソールに、操作ごとの状態（complete / incomplete / error）、字数、出力トークン数が出ます。
- `_workingspace/ai_writer/phase1/<実行日時>/` に、生成の記録（JSON）が保存されます。記録には生出力・整形後の本文・切り落とした範囲と理由・検査（Guard）の結果が入ります。
- 3 操作の確認（`ai_writer_writer_cli.py`）で生成した文は、候補として `_workingspace/ai_writer/candidates/<候補ID>/` にも保存されます。候補には、使った部品の版と参照した場面ファイルのハッシュ（Generation Manifest）が付きます。
- 比較実験では、読み比べ用の `review.md`、採点用の `scores.csv`、集計の `report.md` が保存されます。

---

## 生成の流れ

ユーザーが操作と本文を指定すると、Monogatari Coach は次の順に処理します。

```mermaid
flowchart LR
  A[操作と本文] --> B[Router: モデルを決める]
  B --> C[PromptRenderer: 要求を組み立てる]
  C --> D[Provider: NovelAI へ送る]
  D --> E[後処理: 余計な出力を切る]
  E --> F[Guard: 機械的な検査]
  F --> G[候補として保存]
```

- **Router**: 操作ごとに使うモデルを決めます。既定は 3 操作とも GLM-4.6 です。モデルを明示したときは、そのモデルが使えなくても別のモデルへ黙って切り替えません。
- **PromptRenderer**: 操作に合う指示文と出力上限を組み立てます。版（現在 `nai-r2`）を記録に残します。
- **Provider**: NovelAI への送受信を受け持ちます。途中で止めた生成も、止めた時点までの本文を「incomplete（途中まで）」として残します。
- **後処理**: モデルが本文の後ろに書き足す解説・自己採点・区切り（`***` など）を切り落とします。切った範囲と理由は記録に残り、生出力も保存されるので、元の文は失われません。
- **Guard**: 元の本文や設定にない人物名・数値、指示文の混入、冒頭での本文の繰り返しを機械的に指摘します。指摘だけで本文は書き換えません。3 操作の確認では、場面の登場人物と既知の事実を「既に知っている名前」として使います。

操作と既定の方式は次のとおりです。

| 操作 | 内容 | 既定モデル |
| --- | --- | --- |
| Continue | 本文の続きを、指示なしでそのまま書かせる | GLM-4.6 |
| Directed Continue | 目的・必ず含めるもの・禁止事項・終わる位置（Beat Contract）を指定して続きを書かせる | GLM-4.6 |
| Expand（Insertion） | 文と文の間に、情景や感情の細部を挟ませる | GLM-4.6 |

既定を GLM-4.6 にしているのは、Phase 0 の日本語 Benchmark で 3 操作とも GLM-4.6 の評価が上だったためです。

---

## コマンド

どのコマンドも、`--execute` を付けない限り送信しません。まず dry-run で内容を確認してから本番を実行します。

### `ai_writer_provider_cli.py` — 接続の確認

NovelAI に短い生成を 2 回送り、最後まで受け取れるか（complete）と、途中で止めたときに部分出力が残るか（cancel）を確認します。

```bash
# 確認（dry-run）— 送信内容を表示する。トークンは伏せる
uv run python tools/ai_writer_provider_cli.py

# 本番 — 2 回送信する（--check で片方だけにもできる）
uv run python tools/ai_writer_provider_cli.py --execute
```

実行後、`_workingspace/ai_writer/phase1/<実行日時>/provider_check.json` に結果が保存されます。

### `ai_writer_writer_cli.py` — 3 操作の確認

固定の場面（`daily`、`battle` など 7 種）を使って、3 操作を 1 回ずつ生成します。生成した文は Guard で検査し、候補として保存します。

```bash
# 確認（dry-run）— 操作ごとのモデル・送信内容・出力上限を表示する
uv run python tools/ai_writer_writer_cli.py --scene daily

# 本番 — 3 回送信する（--op で操作を絞る。--model xialong-v1 でモデルを明示する）
uv run python tools/ai_writer_writer_cli.py --scene daily --execute
```

実行後、コンソールに操作ごとの状態・字数・Guard の判定（pass / warning / fail）と指摘、候補 ID が表示されます。生成の記録は `_workingspace/ai_writer/phase1/<実行日時>/writer_<操作>.json` に、候補は `_workingspace/ai_writer/candidates/<候補ID>/` に保存されます（`record.json`・生出力の `raw.txt`・整形後の `output.txt`・レビューの状態の `review.json`）。

### `ai_writer_bench_cli.py` — 日本語 Benchmark

7 場面 × 3 操作 × 2 モデル × 3 回（計 126 回）を生成し、採点と集計の材料を作ります。

```bash
# 確認（dry-run）— 回数と操作ごとの送信内容を表示する
uv run python tools/ai_writer_bench_cli.py plan

# 本番 — 直列で送信する。止まったら --resume <保存先> で続きから
uv run python tools/ai_writer_bench_cli.py run --execute

# 採点後に集計し直す（送信しない）
uv run python tools/ai_writer_bench_cli.py report _workingspace/ai_writer/phase0_bench/<実行日時>
```

実行後、`_workingspace/ai_writer/phase0_bench/<実行日時>/` に `review.md`（読み比べ）、`scores.csv`（採点欄）、`report.md`（集計）ができます。採点の基準は [rubric.md](../../tools/ai_writer/fixtures/benchmark/rubric.md) です。

モデル名と一次点を伏せた独立採点のシートを作るとき、また一次点と独立点を照合するときは、次を使います（どちらも送信しません）。

```bash
# 独立採点用シート（試行 #1 の 42 件）を blind/ に作る
uv run python tools/ai_writer_bench_cli.py blind _workingspace/ai_writer/phase0_bench/<実行日時>

# 一次点と独立点を照合し、食い違う件を blind/compare.md に出す
uv run python tools/ai_writer_bench_cli.py compare _workingspace/ai_writer/phase0_bench/<実行日時>
```

### `ai_writer_length_cli.py` — 字数不足への対処の比較

Directed Continue の字数を目標に近づける方法（指示字数の倍率、Expand での補完）を比べます。

```bash
# 確認（dry-run）— 条件ごとの指示字数・出力上限と回数を表示する
uv run python tools/ai_writer_length_cli.py plan

# 本番（最大 70 回）。--condition で条件を絞る
uv run python tools/ai_writer_length_cli.py run --execute

# 採点後に集計し直す（送信しない）
uv run python tools/ai_writer_length_cli.py report _workingspace/ai_writer/phase1_length/<実行日時>
```

実行後、`_workingspace/ai_writer/phase1_length/<実行日時>/` に `review.md`・`scores.csv`・`report.md` ができます。

### `ai_writer_validator_fixture_cli.py` — Validator Fixture の検査

意味の検査（Validator、Phase 2 で導入予定）を評価するための正解ラベル付きの例（26 件）を検査します。送信しません。

```bash
# Fixture の形式と整合を検査し、件数を表示する
uv run python tools/ai_writer_validator_fixture_cli.py validate

# 予測ファイル（JSON）を採点する
uv run python tools/ai_writer_validator_fixture_cli.py score predictions.json
```

### `ai_writer_creative_cli.py` — 別の展開を見る（試作）

同じ出発点（本文の末尾）から、指定したモデルで独立した続きの案を複数作り、読み比べ用に保存します。通常の 3 操作とは違い、作者が思いつかなかった展開や表現を見つけるための機能です。

- **モデルは毎回指定します**（`--model glm-4-6` または `--model xialong-v1`）。指定したモデルで失敗しても、別のモデルへは切り替えません。
- **守ること**（既に起きた出来事・既知の事実。`--fixed` で追加）と、**自由にしてよいこと**（既定は「分岐点から先の行動、会話、選択、結末」。`--free` で指定）を分けて渡します。
- 案の数は既定 3、最大 5 です。1 案ごとに独立した要求を送り、前の案を次の案に混ぜません。

```bash
# 確認（dry-run）— モデル・送信内容・生成回数を表示する（Benchmark の場面を出発点にする例）
uv run python tools/ai_writer_creative_cli.py plan --scene romance --model xialong-v1

# 本番 — 3 案を順番に生成する。Ctrl+C で止めると、生成中の案は途中まで保存し、残りは送らない
uv run python tools/ai_writer_creative_cli.py run --scene romance --model xialong-v1 --execute

# 自分の本文ファイルを出発点にし、作品の character.md / world.md を既知の名前として読む（作品フォルダには書き込まない）
uv run python tools/ai_writer_creative_cli.py run --text-file start.md --work-dir novels/NNN_作品名   --model glm-4-6 --fixed "二人はすでに別れている" --free "再会の理由" --execute
```

実行後、`_workingspace/ai_writer/creative/<実行日時>/` に次のファイルができます。

- `review.md`: 守ること・自由にしてよいこと・出発点の本文と、案ごとの本文。Guard の指摘や、確認が要る場面転換（`***`）も並びます。
- `evaluation.csv`: 案ごとの評価欄（自然度・魅力・意外性・採用したい範囲など）。記入して保存すると、作り直しても消えません。
- `group.csv`: 案の群としての評価欄（案どうしの違い・使いたい案があったか・読み比べの時間）。
- `candidates/<候補ID>/`: 案ごとの生出力・整形後の本文・記録。

途中で止めた探索は、続きから再開できます。成功済みの案は飛ばし、まだ作っていない案だけを作ります。途中で止まった案や失敗した案を作り直すときは、`--retry-incomplete` を付けます（新しい ID で作り、元の案は残ります）。

```bash
# 確認（dry-run）— 作る案の番号を表示する
uv run python tools/ai_writer_creative_cli.py resume _workingspace/ai_writer/creative/<実行日時>

# 本番
uv run python tools/ai_writer_creative_cli.py resume _workingspace/ai_writer/creative/<実行日時> --execute

# 評価欄を記入したあと、review.md などを作り直す（送信しない）
uv run python tools/ai_writer_creative_cli.py review _workingspace/ai_writer/creative/<実行日時>
```

案の中の新しい人物や過去の出来事は「追加の候補」で、作品の設定には入りません。気に入った案を本文に使う手順（採用と設定の確認）は Phase 2 以降で用意します。

### `ai_writer_creative_bench_cli.py` — 別の展開を見る 実験A

「別の展開を見る」で GLM-4.6 と Xialong のどちらが役立つかを、6 つの固定課題（対人の迷い・探索・危機・恋愛・コメディ・SF）で比べます。課題ごとに両モデルで 3 案ずつ作ります（計 36 回）。両モデルに同じ要求を送ります。

```bash
# 確認（dry-run）— 回数・実行順・送信内容を表示する
uv run python tools/ai_writer_creative_bench_cli.py plan

# 本番（36 回、直列）。止まったら --resume <保存先> で続きから
uv run python tools/ai_writer_creative_bench_cli.py run --execute

# 採点後に集計する（送信しない）
uv run python tools/ai_writer_creative_bench_cli.py report _workingspace/ai_writer/creative_bench/<実行日時>
```

実行後、`_workingspace/ai_writer/creative_bench/<実行日時>/blind/` に、モデル名と順番を伏せた採点シート（`review.md`）と採点欄（案ごとの `candidates.csv`、群ごとの `groups.csv`）ができます。対応表 `key.json` は採点を保存するまで開きません。採点の基準は [rubric.md](../../tools/ai_writer/fixtures/creative/rubric.md) です。

### Phase 0 の確認用コマンド

NovelAI の API 仕様を確かめたときのコマンドです。通常の利用では使いません。

- `ai_writer_spike_cli.py`: 送り先・応答形式・文脈長・同時実行数などの確認（`plan` / `run --execute`）
- `ai_writer_expand_spike_cli.py`: Expand の方式比較（`plan` / `run --execute` / `rescore`）

---

## 現在できないこと・注意

- **作品の本文へは書き込みません。** 生成結果は候補として `_workingspace/` や候補の保存先に残るだけです。本文への反映は、Phase 2 で導入予定の採用（Accept）と Canon Gate（新しい設定を人が確認する関門）を通します。
- **Guard は機械的な検査だけです。** 物の状態の矛盾（箸を置いた直後に箸を握る）や、名前のない新しい出来事は見つけられません。意味の検査は Phase 2 で導入予定です。
- **Xialong は既定にしていません。** Benchmark で、指定した終わる位置を越えて書き続ける傾向が強かったためです。使う場合は `--model xialong-v1` で明示します。
- **同時に生成できるのは 1 本だけです。** NovelAI の Web 画面で生成している最中に送ると、待ってから送り直します。
- **Directed Continue の字数**: GLM-4.6 では、目標字数の 1.5 倍を指示しています（目標 400 字なら「約 600 字」と指示）。何も調整しないと目標の約 6 割で終わってしまうためです。目標の判定には元の目標字数を使います。

---

## 用語

- **Capability Profile**: モデルごとの能力の表です。実測した値と推測の値を区別して記録します（`tools/ai_writer/profiles/`）。
- **候補（Candidate）**: 生成結果の保存単位です。生成の状態（complete / incomplete / error）とレビューの状態（未確認・選択・却下・採用）を別に持ちます。再生成しても前の候補は上書きされません。
- **Generation Manifest**: 1 回の生成について、使ったモデル・部品の版・参照した設定ファイルのハッシュを記録したものです。あとで設定ファイルが変わったことを検出できます。

開発者向けの実装は `tools/ai_writer/` にあります（`provider.py`、`writer.py`、`guard.py`、`candidates.py` など）。
