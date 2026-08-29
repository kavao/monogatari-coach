---
name: novel-reader-walk
description: >-
  一般読者ペルソナが本文を場面ごとに読み、その時点の感想と突っ込みだけを
  novels/.../_reader/walk/ へ追記する。既定は未読の残り全部。要望があれば指定範囲。
  採点・足切りはしない。チャットには範囲と通しの要約だけを返す。
targets: ["*"]
---

## 目的

Reader Walk（読み進み）で、感想の所在と進行位置を曖昧にしない。

横断正本は **`.rulesync/rules/workflow-specification.md`** の「評価ファイル命名と役割」および「Reader Walk Mode」。短い完了条件は **`.rulesync/rules/concepts.md`** の「完了扱い条件」。このスキルは、場面ごとに感想を追記しながら指定範囲（既定は未読の残り全部）を読み進める実行手順を定める。

書き方の技法は `_how_to/reader_walk.md` を読む。**無いときは `_how_to.example/reader_walk.md` を使う。** ペルソナは、明示指定が無い場合は **`readers/000_default/reader_preferences.md`**、追加ペルソナを指定した場合は `readers/<persona_id>/reader_preferences.md` を正とする。

**重要**: 足切りは **`novel-reader-output`**、深掘り採点・一貫性監査は **`novel-evaluation-output`** が正とする。本スキルはそれらを上書きしない。

## 保存先（必須）

| 役割 | パス |
|------|------|
| 感想正本（追記専用） | `novels/<作品>/_reader/walk/journal.md` |
| 到達位置・次に読む箇所 | `novels/<作品>/_reader/walk/state.md` |
| 追加ペルソナの状態 | `novels/<作品>/_reader/walk/state/<persona_id>.md` |

- `_reader/walk/` が無ければ作成する。
- First Reader の `_reader/YYYYMMDD_HHMM.md` や Interest Check とファイルを混ぜない。
- チャットに感想を出しただけでは完了ではない。
- `state.md` は既定ペルソナまたは現在のアクティブ状態として後方互換で残す。追加ペルソナの状態は `state/<persona_id>.md` に分け、別ペルソナの到達位置を上書きしない。

## 反応メタデータ（定量化モード）

ペルソナ差を比較したいときは、感想本文の直後に次の固定順・固定キーのブロックを追記する。これは作品の評価点ではなく、**そのペルソナが既読場面で受けた反応の記録**である。通常の Reader Walk と同様、数値をチャットへ出さない。

```markdown
- **scene_id**: `ch01-003`
- **persona_id**: `000_default`
- **session_id**: `20260830_000_default`
- **reaction_intensity**: `4`
- **reaction_valence**: `mixed`
- **reaction_tags**: `["curiosity", "tension"]`
- **continuation_pull**: `5`
```

- `scene_id`: `<!-- scene: chNN-MMM -->` のアンカー値を優先する。アンカー値は `chNN-MMM` の形式にする。無い場合は、入力本文のファイル名（拡張子を除き、ID許可文字以外を `_` に置換）と場面出現順をつないだ `source_file_stem-sNNN`（例: `novel_text01-s001`）とする。見出し文言を集計キーにしない。
- `persona_id`: `readers/` のペルソナID。
- `session_id`: 一つの読み進みセッションを識別する。同じペルソナの再読は新しい値にする。
- `reaction_intensity`: 感情の大きさ。0〜5の整数で、0はほぼ無反応、3は感情の動きが明確、5は強い感情のピーク。怒り・不安・悲しみも含む。
- `reaction_valence`: `positive` / `negative` / `mixed` / `neutral` のいずれか。
- `reaction_tags`: 固定語彙から1〜3個をJSON配列で記録する。順序は `curiosity` → `tension` → `surprise` → `joy` → `relief` → `sadness` → `anger` → `fear` → `confusion` → `boredom` → `admiration` とする。`reaction_valence` とタグの組み合わせは独立項目として許容する。
- `continuation_pull`: 次を読みたい強さ。0〜5の整数で、0は止めたい／飛ばしたい、3は時間があれば続けたい、5はすぐ次を開きたい。感情の強さとは分けて記録する。

定量化モードでは7項目を必須とする。既存の定量化前ジャーナルを検査するときだけ `python tools/novel_reader_walk_check.py <journal.md> --allow-missing-reaction` で反応ブロックの無い旧エントリをWARNINGとして許容できる。

`rising` / `falling` / `flat` / `peak` は本文へ手で書かず、`tools/novel_reader_walk_check.py` が同じ `(session_id, persona_id)` のジャーナル出現順から生成する。`rising` は直前との差分が+1以上、`falling` は-1以下、`flat` は0。`peak` は強度4以上で利用可能な前後の場面以上の局所最大とし、同点の連続は先頭だけを採用する。先頭の推移は `null`、末尾や1場面だけの範囲は利用可能な近傍だけで判定する。生成した trace は `reaction_trace.json` などの副本であり、`journal.md` が正本である。

## セッション手順

**既定の範囲は未読の残り全部**である。ユーザーが章・プロローグ・場面など範囲を指定したときだけ、その領域で止める。ジャーナルは場面ごとに1エントリずつ追記する。途中で「次へ進みますか」と止めない。

### 開始時

最初に対象ペルソナを決める。指定が無ければ `000_default` とし、追加ペルソナが明示された場合はそのIDを使う。対象ペルソナに応じて状態ファイルを次のように固定する。

- `000_default`: `walk/state.md`
- 追加ペルソナ: `walk/state/<persona_id>.md`

範囲指定が無く、対象ペルソナの状態ファイルが無い場合は、既定ペルソナの終端状態を引き継がず、本文の最初の未読場面から開始する。これにより、既定ペルソナが読了済みでも新しいペルソナの読み進み位置を独立して持てる。

次の順で読む。

1. 対象ペルソナの状態ファイル（無ければ初回として扱う）
2. `walk/journal.md` の対象ペルソナに属する最新エントリ（前回の口調と未回収の疑問）
3. 対象ペルソナの `reader_preferences.md`
4. 対象範囲の本文。範囲指定がなければ対象ペルソナの状態ファイルの「次に読む箇所」から最終ファイルまで。状態ファイルが無い初回は本文の最初から読む。指定があればその領域だけ。

場面の単位は、本文の `<!-- scene: chNN-MMM -->` を優先する。無いときは章内の場所・時間・視点の切れ目を1単位とし、対象ペルソナの状態ファイルに「次はどこから」を残す。

指定範囲の外は読まない。`character.md` / `world.md` / `design_specification.md` を根拠に本文を訂正しない。

### 追記

1. `_how_to/reader_walk.md`（無ければ `_how_to.example/reader_walk.md`）に従い、進めた各場面を `journal.md` へ1エントリずつ追記する。
2. 範囲の最後で対象ペルソナの状態ファイルの到達場面・次に読む箇所・今の気分・未回収の疑問を更新する。既定ペルソナは `state.md`、追加ペルソナは `state/<persona_id>.md` とする。初回なら次の雛形で作成する。

```markdown
# Reader Walk 状態

- **ペルソナ**: readers/<persona_id>
- **到達場面**: ch01-001
- **次に読む箇所**: `novel_text01.md` の ch01-002
- **今の気分**: （短い一言）
- **未回収の疑問**: （読者がまだ気にしている点。無ければ「なし」）
- **読了**: 未
```

3. **`Read`** で追記箇所を確認する。確認前に完了を告げない。

4. 反応メタデータを1つでも追記した定量化モードでは、`Read` の後にcheckerを実行する。

```bash
python tools/novel_reader_walk_check.py <walk_dir>/journal.md \
  --trace-output <walk_dir>/reaction_trace.json
```

checkerのERRORが0であることを確認してから完了とする。定量化前の旧エントリを移行する場合だけ `--allow-missing-reaction` を付け、WARNINGが残る移行途中であることを記録する。定量化を新規に始めたセッションでは、`--allow-missing-reaction` なしで終了コード0になることを完了条件とする。

定量化モードでは、同じ `(session_id, persona_id, scene_id)` を二度登録しない。同じペルソナの再読は `session_id` を変え、旧エントリを保持する。

### チャットで返すもの

- 進めた範囲（開始場面〜終了場面、件数）
- 通しの感想要約 2〜6行
- 保存先パス（`walk/journal.md` と対象ペルソナの状態ファイル。既定は `walk/state.md`、追加ペルソナは `walk/state/<persona_id>.md`）
- 定量化モードでtraceを生成した場合は `walk/reaction_trace.json` の保存先
- 範囲指定で途中停止した場合のみ「続きの範囲を指定するか、残り全部を読むか」

ジャーナル全文はチャットに出さない。点数・改善点リストは出さない。

### 読了

指定範囲の最終場面を追記したあと、対象ペルソナが作品本文の最終場面まで到達していれば、そのペルソナの状態ファイルの **読了** を完了にする。既定ペルソナは `state.md`、追加ペルソナは `state/<persona_id>.md` へ記録する。途中範囲で止めた場合は読了にしない。

## 禁止

- 採点、足切り判定、Editor Score 形式の改善提案
- 指定範囲の外を読むこと
- 設定資料を根拠にした本文訂正（読者が既読範囲で「さっきと違う」と感じた突っ込みは残してよい）
- First Reader / Interest Check のファイル名への混入
- 宣言だけで `walk/` を更新せず応答を終えること

## 査証ログ

`_workingspace/log/` には「どの作品のどの場面まで読んだか」と保存先だけを追記する（スキル **`workspace-audit-log`**）。感想本文は査証ログに置かない。

## 関連

- 足切り・興味判定: **`novel-reader-output`**
- 深掘り採点・一貫性監査: **`novel-evaluation-output`**
- 査証ログ: **`workspace-audit-log`**
- 概念正本: `.rulesync/rules/concepts.md` の「完了扱い条件」
- 横断仕様: `.rulesync/rules/workflow-specification.md` の「評価ファイル命名と役割」
- 操作説明: `docs/workflow/reader-output.md`
