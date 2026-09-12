---
name: novel-story-reflection
description: >-
  執筆・清書・加筆の直後に、本文の内容を _meta.md や design_specification.md へ反映し、
  作品全体の進捗とプロットの整合性を同期する。
  「執筆完了」報告の前に必ず実行し、文脈の「ずれ」を未然に防ぐ。
targets: ["*"]
---

## 目的

執筆した内容が「書きっぱなし」になり、メタ情報（進捗・文字数・次回タスク）や設計書（プロット）と乖離するのを防ぐ。エージェントは本文保存の直後に本スキルを適用し、常に最新の「作品の状態」をファイルに刻む。

## 発動タイミング

経路は一つ。`publish` した直後に `_novel_text` を手編集し直してから本スキルを重ねない。

- **本文の新規執筆・追記・挿入**（スキル **`novel-text-file-output`** の従来経路）の直後。
- **writing_bridge `publish`** で `_novel_text` を更新した直後（CLIは `_meta.md` を書き換えない。句読点は `report.json` を確認済みであること）。
- **清書・文章校正**（スキル **`novel-refinement-output`**）の直後。
- セッションの終了時（引き継ぎ準備）。

修復中（`repair-*` のみで正本未更新）は本スキルを起動しない。

journal / lock / 設計書 / `_meta.md` の原子更新は手編集しない。`python tools/story_reflection_op.py` を使う。

## 同期プロトコル（手順）

### 1. 定量情報の更新（_meta.md）
- **文字数**: `python tools/novel_char_count.py` を実行し、最新の数値を `_meta.md` の「現在の章・項」節へ反映する。
- **進捗率**: 全体の章立てに対する現在の到達度を更新する。

### 2. 定性情報の反映（_meta.md）
- **直近の重要イベント**: 今回書いたシーンで「何が確定したか」「どんな感情が動いたか」を 1〜2 文で追記・更新する。
- **次回のタスク**: プロット（`design_specification.md`）を参照し、次に書くべき内容を具体的にセットする。
- **伏線・フラグ**: 新たに発生した伏線や、今回回収したフラグをメモする。
- **出来事同期**: 手順3の判定結果を1行残す。長文の出来事リストは置かない。

### 3. 設計書との整合（design_specification.md）

`_meta.md` の進捗更新だけで完了扱いにしない。対象章を一意に解決し、その章（または項）の**確定出来事**を本文と突き合わせる。

#### 3.1 対象の解決（推測しない）

本文側の番号はファイル名だけを使う。見出し類似度では決めない。

```text
novel_text(\d+)(?:_(\d+))?\.md
```

設計書側のアンカー:

```text
章: ^#{2,4}\s*第\s*(\d+)\s*章(?!\s*第?\s*\d+\s*項)(?!\d)
項: ^#{2,6}\s*第\s*(\d+)\s*章\s*第?\s*(\d+)\s*項
```

解決は `python tools/story_reflection_op.py resolve novels/<作品> --text novel_textNN.md` に任せる。解決不能は同期せず、完了報告しない。

| 本文 | 書き換える範囲 |
| --- | --- |
| `novel_textNN.md` | 章アンカー第N章。章が無く項だけなら全項の確定を集約する。章見出しは新設しない |
| `novel_textNN_Y.md` | 項アンカー第N章Y項。項が無く章だけなら章アンカー配下を一章一分として更新する。項見出しは新設しない |
| 章＋項が共存し `novel_textNN.md` | **章アンカーだけ**。項は保持する。項へ分配しない |
| 章＋項が共存し `novel_textNN_Y.md` | **対応する項アンカーだけ**。章アンカーは保持する |

同一 operation で章アンカーと項アンカーの両方を書き換えない。章直下が空で項だけがあるときは、章側へ短い確定要約を1項目書いてよい。新しい見出しを作らない。章アンカー同士の同一N、項アンカー同士の同一(N, M)は重複として停止する。章と項の共存は重複ではない。

#### 3.2 確定と予定

見る差分は転換点だけではない。手順、回数、時間、禁止事項、建前、境界、誰が何をした、到達した／しなかった行為を含む。

- 確定ブロックだけを現行本文へ合わせる。古い確定文言は残さない。
- 予定ブロックは章完了前に削除しない。部分稿は書いた範囲だけ確定化する。
- 番号リストにラベルが無いときは、本文から言える項目を確定、未執筆を予定として扱う。

#### 3.3 暗黙承認の範囲

ユーザーが本文の新規執筆・追記・清書・改稿を指示した時点で、**解決できた対象章（項）の確定出来事**、同じ章の実文字数・状態、`_meta.md` の進捗・直近イベント・出来事同期1行は相談不要。追加の「設計書も直しますか」は挟まない。

自動変更しない:

- テーマ、コンセプト、制約、到達深度、将来章、未解決の他章
- `character.md` / `world.md`（波及が必要なら相談）
- CHRONOS イベント YAML、METRON の `beats.yaml` / `contract.yaml`
- 予定ブロックの削除、章見出しの新設、部構成の組み替え

同期せず `未完了` または相談にする場合:

- ユーザーが設計書更新を明示的に禁止した
- 本文が作品の不変条件へ抵触する
- 確定として書く内容が、対象範囲の本文から一意に言えない
- ユーザーが言っていない大幅なプロット変更

#### 3.4 更新 / 差分なし / 未完了

- **更新**: 現行本文の確定事実が設計書の確定と食い違う。旧版は必須にしない。初稿の新規保存はこれにあたる。
- **差分なし**: 対象範囲を通読し、旧版根拠と比較して事実が変わっていないときだけ。根拠は (1) `_novel_text_backup/<元ファイル名>_vNNN.md` の直前版、(2) `publish` の採用前本文。どちらも無いときは `未完了（旧版根拠なし）` とし、`差分なし` にしない。現行設計書と現行本文だけを見て `差分なし` としない。設計書も確定ブロックも書き換えない。
- 文体・テンポ・情景密度・章メタ除去・誤打修正だけで事実が変わらなければ `差分なし` とし、確定ブロックを全置換しない。
- 末尾だけ読んで判定しない。項分割の予定判定は第N章の全項を読む。

#### 3.5 書込み手順（CLI 必須）

手の Read → 判定 → 置換は禁止する。ロック無しの更新は未完了とする。本文は同期失敗でも戻さない。各コマンドは読込から全書込み完了まで OS 排他（`flock` / `msvcrt.locking`）を保持する。lock ファイルの存在だけでは並列コマンドを止めない。新規 lock は staging に書いて OS ロックを取ってから正式名へ公開する。POSIX は `link`、Windows は staging の `rename`（宛先が無いときだけ）。既存正式名があれば `LOCK_HELD` とし、既存を置換しない。削除は正式名が消えるまで排他を保持し、fd が同一ファイルと operation id を所有しているときだけ行う。削除 API が失敗したら正式名は残し `LOCK_HELD` とする（`.dead` へ rename しない）。`resume` は active だけを対象にし、三系統ハッシュを再照合してから current を写す。

1. `inspect` で current / 最後の状態遷移 / lock を見る。孤児（`ORPHAN`）なら新規同期も自動完了もしない。ユーザーが明示したときだけ `resume`（active のみ）または `close-orphan`（active の孤児のみ）。`done` / `failed` は `resume` しない。
2. 入力ハッシュと意図ハッシュを `hash` で取る。対象本文は項作業なら第N章の全項ファイルを含める。
3. `begin` で新規 `prepared(transition_seq=1)` だけを追加する。既存の `done` / `failed` は検証するだけで、状態遷移として再追記しない。`journal_seq` は継続する。active 中は `JOB_CONFLICT` / `未完了（同期中の operation あり）`。lock 取得不能は `未完了（同期ロック取得不能）`。lock を盗まない。
4. **更新**なら意図した設計書全文を `--file` に渡し `apply-design`。対象範囲以外は読込文面のまま保持する。テーマ・将来章・制約は動かさない。
5. **差分なし**（旧版根拠あり）なら設計書は置換せず、`intended_design_sha256` を入力と同じにして `apply-design`（変更なしで `verified`）する。
6. 意図した `_meta.md` を `apply-meta`。設計書より先に完了証跡を書かない。`verified` のあとだけ。
7. 各遷移で設計書・`_meta.md`・対象本文を再照合する。ずれは `failed` / `未完了`。完了証跡を書かない。
8. `done` / `failed` のあと lock が残ったら、チャットの「消して」だけでは消さない。`lock-inspect` で terminal 一致を確認してから `lock-release`。`lock_released` は正式名の削除成功後だけ journal へ追記する。削除失敗では成功イベントを残さない。active / 孤児は解除不可。

```bash
python tools/story_reflection_op.py inspect novels/<作品>
python tools/story_reflection_op.py resolve novels/<作品> --text novel_text18.md
python tools/story_reflection_op.py hash novels/<作品>/design_specification.md
python tools/story_reflection_op.py begin novels/<作品> --evidence evidence.json
python tools/story_reflection_op.py apply-design novels/<作品> --file intended_design.md
python tools/story_reflection_op.py apply-meta novels/<作品> --file intended_meta.md
python tools/story_reflection_op.py fail novels/<作品> --reason STALE_EVIDENCE
python tools/story_reflection_op.py lock-inspect novels/<作品>
python tools/story_reflection_op.py lock-release novels/<作品>
```

CLI の終了コード 0 以外は未完了。`確認済み` だけでは完了にしない。

実文字数・状態は、設計書に「執筆スケジュール」等の表があるとき、`novel_char_count.py` の計測で該当章と合計を更新する（空欄のままにしない）。章分割ファイルを足したときは章立て・スケジュールへ反映する。機械的なズレ検出には `python tools/novel_project_check.py <作品> --check-story-sync` を補助に使える。意味一致の正本にはしない。

### 4. 査証ログへの記録
- 対象作品の `config.md` に `AUDIT_LOG | OFF` があるときは追記しない。行なしまたは ON のときだけ、文字数と同期内容を `_workingspace/log/YYYYMM.md` に追記する（スキル **`workspace-audit-log`**）。`--novel novels/<作品>` を付ける。
- 作品が OFF でも journal（`_story_reflection_op.json` / `.jsonl`）は省略しない。

### 5. 挿絵・表紙・出版メタの同期（該当時）

本文以外の作業（挿絵生成・題字採用・cover 合成・proof export）の直後にも、次を `_meta.md` へ反映する。

- **§3.1**: 表紙の計画状態、題字方針、題字ロゴ状態
- **§3.2**: 章挿絵の計画／YAML／生成列（挿絵タスク時）
- **§7 出版パッケージ進捗**: book / rights / cover.yaml / lock / interior / reader-proof / preflight / 最新 build-id

出版の完了条件の正本は **`.rulesync/rules/workflow-specification.md`** の「出版完成目安」。スキル **`novel-cover-layout`** / **`title-logo-plan`** 完了時は本節を必ず更新する。

## 完了の定義（ストーリー反映）

ユーザーに「執筆完了」を伝える際には、次の要素が揃っていることを条件とする。

1. 本文が保存・確認されている（`novel-text-file-output`。`publish` 経路を含む）。
2. **`_meta.md` が最新の状態に更新されている**（本スキル手順1, 2）。
3. 対象章または項を手順3.1で解決し、確定出来事を突き合わせ済みである。結果は `更新` または旧版根拠付きの `差分なし`。解決不能・旧版根拠なし・lock / journal / ハッシュ不一致・孤児は **未完了で停止**し、完了報告しない。
4. `_meta.md` に出来事同期1行がある。チャット末尾の一行は副本である。
5. 次回タスクが明文化されている。

完了報告例（章ごとに1行。出来事本文は複製しない）:

`反映: _meta.md / design_specification 実文字数 / 第18章出来事（更新）`

`反映: _meta.md / design_specification 実文字数 / 第18章出来事（差分なし）`

`反映: 第18章出来事（未完了：章アンカー重複）`

永続正本の形式:

```text
- **出来事同期**: 2026-09-12 第18章 更新（規定時間60秒の十往復） op=sr-…
- **出来事同期**: 2026-09-12 第18章 差分なし（文体のみ） op=sr-…
- **出来事同期**: 2026-09-12 第18章 未完了（章アンカー重複） op=sr-…
```

## 関連スキル

- 本文保存: **`novel-text-file-output`**
- 清書・退避: **`novel-refinement-output`**
- 執筆接続: **`.rulesync/rules/workflow-specification.md`** の「執筆接続の起動判定」
- 査証ログ: **`workspace-audit-log`**
- 企画・設計: **`novel-planning`**
- 機械操作: `tools/story_reflection_op.py`
