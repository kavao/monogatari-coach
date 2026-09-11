# writing_bridge schema 1

接続契約。CLI は `python tools/writing_bridge_cli.py`（prepare / receive / inspect / status / repair-* / publish）。既存の METRON / CHRONOS スキーマへ未定義キーを足さない。

関連計画: `_workingspace/plans/20260909_metron-chronos-writing-integration.md`

## 版互換

- すべての成果物の先頭キーは `schema: 1`（整数）。
- 未知キーは黙って捨てず `UNKNOWN_KEY`。
- 必須キー欠落は `MISSING_FIELD`。
- `schema` が欠ける、または 1 以外は `SCHEMA_UNSUPPORTED`。
- 新しい必須キーを足すときは `schema: 2` にする。1 の読込器は 2 を読まない。

パスは作品ルート相対、`/` 区切り、`..` 禁止、絶対パス禁止。本文パスは作品フォルダ内に限る。

## CLI（固定）

R1（Phase 2）:

| 動詞 | 役割 |
| --- | --- |
| `prepare` | 依頼と入力ハッシュを確定し、context / links 候補を出す。本文を書き換えない。`--allow-publish` で `permissions.publish` を true にする |
| `receive` | 起草候補を依頼 ID と本文ハッシュで取り込む。版別に保存し、同一ハッシュは既存版を再利用する。`--finish-reason` でその版の生成来歴を記録できる |
| `inspect` | 同じ受領候補へ METRON 計測と C1 本文根拠を走らせる。`--marked` は受領候補と同一 raw hash のパスだけ。不一致は `STALE_EVIDENCE`。`--from-run` は `run-\d{4,}` のみ。指定元の `observations.json` が無ければ `UNKNOWN_REF`（保存先の旧根拠へフォールバックしない）。`--observations` が無いとき、指定元の observations を本文 hash 一致なら流用する。不一致は `STALE_EVIDENCE`。同一 `source_raw_sha256` の metrics / spans は版を増やさない。候補が無いときだけ既存 `_novel_text`。未作成の新章は候補必須 |
| `status` | run の journal と各項目状態を表示する |

R2（Phase 3〜4）:

| 動詞 | 内部 API |
| --- | --- |
| `repair-begin` | `begin_repair` |
| `repair-next` | `next_job`（ジョブ／完了／要確認を返して即終了） |
| `repair-submit` | `submit_result` |
| `publish` | 受領済み候補を `_novel_text` へ場面単位で反映する。CHRONOS ON では C1 成功前に正本を書かず `completed` にしない。`FINAL.md` は完了扱いしない |

CLI が LLM を起動したことにはしない。

## ID

| 種類 | 正規表現 | 例 |
| --- | --- | --- |
| scene_id | `^ch\d{2,}-\d{3,}$` | `ch01-001` |
| request_id | `^WRQ-\d{4,}$` | `WRQ-0001` |
| run_id | `^run-\d{4,}$` | `run-0001` |
| job_id | `^JOB-\d{4,}$` | `JOB-0001` |
| event_id | CHRONOS と同じ `^EVT-\d{4,}$` | `EVT-0001` |
| actor_id | CHRONOS と同じ `^CHR-[A-Za-z0-9_-]+$` | `CHR-a` |
| beat_id | METRON と同じ `^[A-Za-z][A-Za-z0-9_-]*$` | `say_goodbye` |
| location_id | CHRONOS と同じ `^LOC-[A-Za-z0-9_-]+$` | `LOC-home` |

`scene_id` と `novel_textNN.md` を番号だけで結び付けない。

## 列挙

| キー | 値 |
| --- | --- |
| `request_kind` | `new` / `append` / `local_expand` / `refine` |
| `state_at` | `before` / `after`（CHRONOS `StateAt` と同じ） |
| `confirmation` | `match` / `mismatch` / `absent` / `unclear` / `unrecorded` |
| `item_status` | `success` / `findings` / `skipped` / `unresolved` / `failed` |
| `links_status` | `adopted` / `candidate` / `conflict` |
| `recorder` | `agent` / `author` / `tool` |
| `selector.kind` | `heading` / `html_comment` / `offset` |
| `journal.action` | `prepare` / `request` / `receive` / `validate` / `inspect` / `select` / `publish` / `repair_begin` / `repair_next` / `repair_submit` |
| `job.operation` | `deepen` / `regenerate` / `seam` |
| `job.status` | `pending` / `accepted` / `rejected` / `failed` / `unknown` |
| `severity` | `error` / `warning` / `info` |

確認状態の日本語対応（報告文だけ。機械キーは英語）:

- `absent` = 記載なし
- `unclear` = 不明
- `unrecorded` = 必須項目の未記録
- `match` / `mismatch` = 引用と CHRONOS 値が一致 / 不一致

`match` 以外は一致件数の分子に入れない。引用・参照・型の検証を通っていない項目は `match` にしない。`RANGE_MISMATCH` のとき `text_state` は `success` にしない。

## ハッシュと座標

| 対象 | 定義 | フィールド |
| --- | --- | --- |
| raw ファイル | ディスク上のバイト列の SHA-256 | `raw_sha256` |
| 正規化本文 | NFC、改行 LF、Beat / fact マーカー除去後の UTF-8 バイトの SHA-256。マーカーだけの行は行ごと落とす | `text_sha256` |
| 範囲 | 正規化本文のコードポイント半開区間 `[start, end)` | `start` / `end` |
| 範囲内容 | そのスライスの UTF-8 バイトの SHA-256 | `range_sha256` |

表記は `sha256:` + 小文字 hex 64 桁。

正規化座標で raw ファイルを直接切らない。原文への反映は、正規化スライスと raw の対応表を別途持つ。対応を再構築できないときは `STALE_EVIDENCE`。

R1: 既存本文スキルが保存したあと `text_sha256` が inspect 対象と違えば、保存は `success`、計測と C1 は `unresolved`（`STALE_EVIDENCE`）。R1 は自動の追従再計測をしない。`publish`（Phase 4）は保存後に同じ run で再計測し、`report.target_text_sha256` を保存本文へ合わせる。C1/METRON は採用した場面稿（マーカー付き）で測る。保存ファイルと場面稿の正規化ハッシュが違うときは findings に記録し、前版 metrics を流用しない。

## 試行上限（修復。R2）

| operation | 上限 | 根拠 |
| --- | --- | --- |
| `deepen` | 同一 Beat 最大 2 | 現行 `run_expand_loop` |
| `regenerate` | 同一 Beat 最大 1 | 現行 `repair_scene` はコールバック 1 回。2 には増やさない |
| `seam` | run 全体で最大 1 | 現行の結合校正。必須修復も追加候補も無い no-op では出さない |

失敗・空出力も 1 試行。job 発行時に枠を予約する。`repair-next` の再取得は同じ `pending` job を返す。同一 job の同一結果の再 submit は冪等。異なる候補の再 submit は `JOB_CONFLICT`。

### Phase 3 永続契約（実装済み）

- `repair_state.json`: 内部版 `version: 1`。request/input/calibrationのハッシュ、修復依頼の出典、元稿と出力版参照、`session`、`status: active|completed|escalated` を保持する。`escalated` は適格追加候補が無くシーン床を止められないときだけ。旧ファイルは `active|completed` のまま読める。任意の `notes` にスキップ理由を残してよい。モデルは `tools/writing_bridge/repair.py` の `BridgeRepair`、セッションは `tools/metron/repair_steps.py` の `RepairSession` が正。`completed` / `escalated` の同一 run へ新ハッシュの `receive` は `JOB_CONFLICT`。新候補は新 run。
- `jobs/JOB-NNNN.json`: `schema: 1`、run_id、`status: pending` と `RepairJob` の全フィールド。operation/beat_id/attempt/model/prompt、input_hash/context_hash/prompt_hashを保持。input_hashは修復直前のBeat本文（seamは全BeatのJSON）、prompt_hashは実際のprompt全体。発行済みファイルは予約時のスナップショットであり、完了状態はsession.historyを参照する。
- 結果はcandidateまたはerrorのいずれかと、実際のmodel、`review: confirmed|unverified|rejected`。CLIと `submit_result` は両方の同時指定を拒否する。意味レビュー未確認・拒否は適用せず履歴へ記録。同一結果の定義は候補全文・error・reviewがすべて同じこと。
- `session.history` は確定結果を保持し、決定的な再投入で次ジョブを再現する。過去のprovider呼出しはない。pendingは予約済みの未確定枠。原子的な状態保存とsceneのOSロックを使う。
- `_metron/<scene>/repair.<run_id>.<確定件数>.md` は固定出力。通常のreceiveでmarked版へ登録する。`_writing` 側へ別の編集正本は増やさない。
- 新版で旧observationsを流用しない。`observations_history/<旧本文hash>.json` へ退避し、再読根拠が揃うまでC1未確認。修復終了は検査成功・本文正本反映を意味しない。

操作例は `docs/architecture/writing-bridge.md`。

### Phase 4 永続契約（実装済み・受入済み）

- `publish` は `permissions.publish` と `--authorization` を必要とする。prepare の `--allow-publish` が無い run は `PERMISSION_DENIED`。active な repair がある run は `JOB_CONFLICT`。既存の非空本文を `request_kind=new` で反映するときは selector、当該場面の `<!-- scene: chNN-MMM -->`、または `append` が必要。無い場合はファイル全体を置換しない。METRON ON の場面作業はエージェントが反映依頼済みと扱う。CLI の `--allow-publish` は技術ゲートとして残す。
- 反映直前と `publish_state.json` 保存後に、正本の存在と raw hash を再確認する。新規のはずのファイルが外部作成された、既存ファイルが削除された、hash が変わった場合は上書きせず `STALE_EVIDENCE`。対象外本文（prefix/suffix）の変化も `STALE_EVIDENCE`。
- publish 開始後の同じ run への `receive` は `JOB_CONFLICT`。inspect は公開済み候補と現在候補の hash が一致するときだけ `text_save=success` を継承する。`--marked` の raw hash が受領候補と違うときは検査せず `STALE_EVIDENCE`。同一バイトの別パスは許可する。
- 既存ファイルは `_novel_text_backup/<元ファイル名>_vNNN.md` へ退避してから `_novel_text` を置換する。未作成の新規は退避しない。`FINAL.md` は作らない。採用したマーカー稿は `_metron/<scene>/adopted.<run_id>.md` に残す。
- 範囲: `request_kind=append` は末尾追加。本文の `<!-- scene: chNN-MMM -->` があればその場面本体。なければ selector（heading / html_comment / offset の `start:end`）またはファイル全体。
- Beat / fact マーカーは正本へ残さない。残っていたら `JOB_CONFLICT`。マーカー除去後の連続空行（Beat境界の隙間）は `normalize_novel_body` で段落1つ分に畳む。
- `publish_state.json`: 内部版 `version: 1`。`status: active|completed`、`stage: backup|write|inspect|done`、候補と意図した本文の hash、退避パス、prefix/suffix。途中失敗は候補と旧稿を残し、同じ authorization で再開する。本文反映済みなら inspect から再開し、二重退避しない。
- 保存後に文字数（`novel_char_count`）と句読点ゲートを記録する。句読点 fail でも本文は戻さない。`text_save` は `success`、指摘は findings。清書 `--fix` と `_meta.md` のストーリー反映は CLI では行わず、既存スキルへ委ねる。
- 完了後に正本が意図した hash と違えば `STALE_EVIDENCE`。同一内容の再 publish は冪等。

## エラー形

単票:

```yaml
schema: 1
code: STALE_EVIDENCE
severity: error
message: base_hash does not match current text
refs:
  path: _novel_text/novel_text01.md
  expected: sha256:...
  actual: sha256:...
```

複数は `errors: [<単票>, ...]`。`code` は次に限る。

| code | 意味 |
| --- | --- |
| `SCHEMA_UNSUPPORTED` | schema 欠落または 1 以外 |
| `UNKNOWN_KEY` | 禁止された余剰キー |
| `MISSING_FIELD` | 必須キー欠落 |
| `BAD_ID` | ID パターン不一致 |
| `BAD_HASH` | ハッシュ表記不正 |
| `STALE_EVIDENCE` | 対象版が変わった、または正規化座標が raw と対応しない |
| `TEXT_STATE_MISMATCH` | 引用は一致するが観測値と CHRONOS before/after が違う |
| `TEXT_STATE_UNVERIFIED` | 未記録・記載なし・不明。一致に数えない |
| `RANGE_MISMATCH` | 引用文字列と `[start, end)` が完全一致しない |
| `LINK_CONFLICT` | links と `source.scene` / `scenes.refs` の矛盾、または CHRONOS 内部の所属矛盾 |
| `PATH_OUT_OF_ROOT` | 作品外・`..`・絶対パス |
| `PERMISSION_DENIED` | 権限表の範囲外 |
| `MODEL_UNCALIBRATED` | 未校正、または実モデル名と校正名の不一致 |
| `JOB_CONFLICT` | 二重 submit・失踪 job の自動再送 |
| `UNKNOWN_REF` | 未登録の event / actor / beat / path。設定エラーと混同しない |
| `CONFIG_ERROR` | フラグ未知値など config.md の読込失敗 |

CHR010〜013 と CHR001 の意味は変えない。本文照合の診断は上表だけを使う。

## 成果物キー

保存先: `novels/<作品>/_writing/<scene_id>/<run_id>/`  
契約・マーカー稿・metrics は `_metron/<scene_id>/`（METRON ON）。

### request.yaml（必須）

| キー | 必須 | 型 |
| --- | --- | --- |
| schema | yes | 1 |
| request_id | yes | WRQ-* |
| run_id | yes | run-* |
| work_rel | yes | 作品フォルダ名（表示用。解決は実行時の作品ルート） |
| scene_id | yes | chNN-MMM |
| request_kind | yes | 列挙 |
| target.text_path | yes | 作品内相対 |
| target.selector | 既稿は yes。新規は receive 後に確定 | object |
| target.base_raw_sha256 | yes | raw。`request_kind=new` で対象ファイル未作成なら空バイトの SHA-256 |
| target.base_text_sha256 | yes | 正規化本文。未作成の新規は空本文の SHA-256 |
| target.base_exists | no | bool。prepare 時点で対象本文が存在したか。未作成は false。存在する空ファイルは true。省略時は true |
| model.id | yes | 実際の生成モデル |
| model.calibrated | yes | bool。設定ファイルの値を写すだけ |
| permissions.draft | yes | bool |
| permissions.repair | yes | bool |
| permissions.publish | yes | bool |
| permissions.event_patch | yes | bool |
| flags.metron | yes | `ON` / `OFF` |
| flags.chronos | yes | `ON` / `OFF` |

R1 の `publish` は false（`--allow-publish` なし）。本文反映は既存スキルまたは Phase 4 の `publish`。`repair` は R1 では false。

### links.yaml（CHRONOS ON で必須）

| キー | 必須 |
| --- | --- |
| schema / scene_id / text_path / selector / text_sha256 | yes |
| status / created_by / adopted_by | yes |
| items[] | yes（0 件は CHRONOS ON では `UNKNOWN_REF` または未確定） |
| items[].beat_id | METRON ON で yes。OFF なら省略可 |
| items[].event_id / state_at / actors[] | yes |
| items[].note | no |

`chronos_span` は参考の両端。区間内イベントの自動全選択はしない。

### context.json（prepare が書く）

必須: `schema`, `request_id`, `run_id`, `input_hashes`（読んだファイルの path＋`raw_sha256`。未作成の対象本文は入れない）, `expected_checks[]`（C1 の分母。event_id / actor_id / dimension / state_at / expected_value）。

CHRONOS ON の `input_hashes` は状態解決と links に使う入力全体を含む。少なくとも `chronos.config.yaml`、`entities/characters.yaml`、`entities/locations.yaml`、`scenes.yaml`、`events/**/*.yaml`、run の `links.yaml`。

`inspect` の前に `input_hashes` を再計算する。ずれていれば context を再構築する。再構築の前後とも prepare と同じ `validate_links()` を通し、現在の CHRONOS と run の `links.yaml` の整合を確認する。対象本文の存在状態（`base_exists`）が変わっていても `STALE_EVIDENCE`。最新の受領候補（`artifact_refs.candidate`）の `raw_sha256` が読み直したファイルと違っても、欠落していても `STALE_EVIDENCE` とし、明示的な再受領を求める。`inspect --marked` で明示した本文も同じ raw hash と照合し、不一致なら計測せず `STALE_EVIDENCE`。同一バイトの別パスは許可する。過去履歴の破損だけでは最新版の検査を止めない。

任意: `beats`, `forbidden`, `instruction_chars`, `chars_floor`（シーンの検査床。任意）, `states`, `unresolved`, `prose_start_end`（`SceneContract` の散文。CHRONOS 値へ変換しない）。`beats[]` の任意キーに `chars_floor`（= `chars_hint`）、`chars_instruction`（hint×1.4 の助言）、`paragraphs`、`dialogue_turns`、`advisory`、`expandable` を足してよい。必須キーは増やさない。倍率は `input_hashes` に入れない。

`context.md` は人間向け副本。機械判定は json を正とする。指示目標は助言であり、検査の床ではない。

### artifact_refs.json

必須: `schema`, `request_id`, `model`。  
任意: `candidate`（最新）、`candidates[]`（受領履歴）、`generation`（その候補版の `finish_reason` / model。`candidate_raw_sha256` で本文版へ結ぶ）。  
METRON ON: `_metron` の contract / beats / marked / metrics / spans への path＋`raw_sha256`。稿は `marked.NNN.md` として版別保存し、既存の `marked.md` は上書きしない。inspect が書く metrics は `source_raw_sha256` / `source_text_sha256` で候補本文へ結ぶ。`finish_reason` の継承は、generation またはその hash が現在候補と一致する metrics だけを使う。別候補を receive したら metrics / spans 参照は外す。  
METRON OFF: `_writing/<scene>/<run>/candidates/candidate.NNN.md` への参照。  
既存版は上書きしない。同一ハッシュの再受領は、そのファイルがディスク上でも一致しているときだけ既存版を再利用する。破損・欠落した履歴は記録として残し、再受領した正常な版を最新にする。

### job（R2。R1 サンプルでは別ファイルで形だけ示す）

必須: `schema`, `job_id`, `run_id`, `operation`, `beat_id`（場面単位の seam は null）, `attempt`, `input_hash`, `context_hash`, `prompt_hash`, `model`, `status`。

本文候補の外に置く。空出力でも残す。`prompt_hash` は context を含む実際の送信文字列。

### observations.json（inspect）

必須: `schema`, `request_id`, `text_sha256`, `expected_total`, `items[]`。  
`items[]` 必須: `event_id`, `actor_id`, `dimension`, `value`, `state_at`, `quote`, `start`, `end`, `range_sha256`, `recorder`, `confirmation`。

`expected_checks` に無い項目だけを分母にして全件一致としない。

### report.json / report.md

必須: `schema`, `request_id`, `run_id`, `target_text_sha256`。  
必須の項目状態: `text_save`, `metron`, `chronos_registered`, `text_state`（いずれも `item_status`）。  
任意: `findings[]`, `repair_history[]`, `open_issues[]`。
`findings[]` の `code` / `auto_repair` は任意。`auto_repair` は METRON 指摘が自動修復対象かどうか。必須キー追加はしない。

### journal.jsonl

1 行 1 オブジェクト。必須: `schema`, `at`（ISO-8601）, `action`, `run_id`。  
任意: `request_id`, `job_id`, `hashes`, `note`。追記のみ。

## サンプル配置

| パス | 内容 |
| --- | --- |
| `ok_ch01_001/` | 中立 1 場面の正常系（METRON ON + CHRONOS ON） |
| `missing_required/` | 必須観測の欠落 → `TEXT_STATE_UNVERIFIED` |
| `invalid_schema/` | 未知キー・不正列挙 |
| `stale_hash/` | 古い `base_text_sha256` → `STALE_EVIDENCE` |
| `examples/job_deepen.yaml` | R2 用 job 形。R1 では実行しない |
