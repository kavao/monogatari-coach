# Reader Output

このガイドでは、下読み・書評・一般読者の興味判定・読み進み感想・深掘り採点・一貫性監査を依頼したときに、Monogatari Coach がどこへ結果を保存し、ユーザーが何を確認すればよいかを説明します。

## このドキュメントを使う場面

小説本文を書いたあと、次のような確認をしたいときに使います。

- 商業的な最低基準を満たしているかを下読みしたい（足切り）
- 冒頭やタイトルで一般読者が読み続けるかを確認したい
- 一般読者として場面ごとに感想を残しながら通読したい（Reader Walk）
- 完稿・推敲後に「どこを直すと何点上がるか」を把握したい（Editor Score）
- 複数章の設定矛盾・口調のブレを洗い出したい（Consistency Audit）
- 長文評価の前に客観的なあらすじを作りたい（Synopsis）

---

## 評価モード一覧

| モード | 指示文（例） | 保存先 | 点数の意味 |
|--------|-------------|--------|------------|
| First Reader（足切り） | `第1章を足切り判定してください。` | `_reader/YYYYMMDD_HHMM.md` | 6項目100点（足切り用） |
| Interest Check | `一般読者視点で興味判定してください。` | `_reader/interest_YYYYMMDD.md` | なし（継続読了 / 離脱） |
| Editor Score | `Editor Scoreで採点してください。` | `_reader/score_YYYYMMDD_HHMM.md` | 5項目100点（改善優先度用） |
| Consistency Audit | `第1〜3章の一貫性を監査してください。` | `_reader/consistency_YYYYMMDD.md` | なし（表形式） |
| Synopsis（前処理） | `あらすじを作成してください。` | `_reader/synopsis_YYYYMMDD.md` | なし |
| Reader Walk（読み進み） | `第1章から読み進めて` | `_reader/walk/<session_id>/journal.md` | なし（感想＋任意の反応メタデータ） |

足切り（First Reader）と Editor Score は配点・目的が異なる別モードです。First Reader は「読むか読まないか」の選別、Editor Score は「どこを直すと何点上がるか」の改善優先度付けです。Reader Walk は採点せず、一般読者として今読んだ場面の感想だけを残します。

---

## First Reader（足切り）

### チャットへの指示文

最小のトリガー文1行で動きます。

```text
第1章を足切り判定してください。
```

段階を指定したい場合は以下のように書き分けます。

```text
# G1: 冒頭（〜3,000字）で速断する
第1章をG1足切りしてください。

# G2: 1章完で判定する
第2章をG2章完足切りで判定してください。

# G3: 全文で判定する
全章をG3全文足切りで判定してください。

# Interest Check と組み合わせる
Interest Check のあと、第1章をG1足切りしてください。
```

### Monogatari Coach が行うこと

`_how_to/reader.md` を参照し、以下の6項目100点満点で評価します。

| 項目 | 配点 |
|------|------|
| 冒頭の牽引力 | 20点 |
| キャラクター | 20点 |
| プロット期待値 | 20点 |
| 文章力 | 15点 |
| わかりやすさ | 10点 |
| 独創性 | 15点 |

採点後、以下の閾値で足切りを判定します。

| 点数 | 判定 |
|------|------|
| 70点以上 | 原則「読むべき」 |
| 55〜69点 | 強い美点が1つ以上あれば「読むべき」（美点を明記） |
| 54点以下 | 原則「読まなくていい」 |

G3（全文）で合計30,000字超の場合は、Synopsis を先行してから評価を開始します（後述）。

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/YYYYMMDD_HHMM.md`
- チャットには「判定・総合点・改善ポイント要約・保存先パス」のみ返ります。
- G1/G2/G3 のどの段階で評価したかは、ファイル内のフロントマターに記載されます。

---

## Interest Check（一般読者の興味判定）

### チャットへの指示文

```text
第1章を一般読者の視点で興味判定してください。
```

### Monogatari Coach が行うこと

`_how_to/standard_reader.md` を参照し、ペルソナを立てたうえで、タイトル・冒頭3行・最初の1ページの第一印象を判定します。

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/interest_YYYYMMDD.md`
- チャットには「判定と一言コメント・保存先パス」のみ返ります。

---

## Reader Walk（読み進み感想）

一般読者ペルソナとして本文を場面単位で読み、その時点で感じたことと引っかかりだけを残します。作品評価の点数は付けません。**指定がなければ未読の残り全部**を進み、章やプロローグなど範囲の指定があればその領域だけ進みます。

### チャットへの指示文

最小のトリガー文1行で動きます。未読があれば、そこから最後まで進みます。

```text
第1章から読み進めて
```

範囲だけ読みたいときは、次のように指定します。

```text
プロローグだけ読み進めて
第2章まで読み進めて
```

### Monogatari Coach が行うこと

指定したペルソナ（指定がなければ `readers/000_default/reader_preferences.md`）の読み手として、指定範囲（なければ対象ペルソナにとって未読の残り全部）を場面ごとに読みます。新規セッションではJSTの `YYYYMMDD_HHMM_<persona_id>` 形式でセッションIDを発行し、感想を `_reader/walk/<session_id>/journal.md` へ場面ごとに追記します。到達位置は同じセッションディレクトリの `state.md` に残します。セッションIDまたはセッションディレクトリを指定した場合は、そのセッションだけを再開します。指定がない場合は、対象ペルソナの読了が未の最新セッションを再開し、該当がなければ新しいセッションを発行します。「新規セッション」「別の読者として」などを明示した場合は、必ず新しいセッションを発行します。

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/walk/<session_id>/journal.md` と同じセッションディレクトリの `state.md`
- チャットには「進めた範囲・通しの要約」のみ返ります。
- ジャーナル全文はチャットには出ません。

### 反応メタデータを記録する場合

ペルソナごとの反応を比較したいときは、`journal.md` に反応メタデータを記録します。これは作品の良し悪しを採点する点数ではなく、その場面でのペルソナ反応です。

`persona_id` と `session_id` は1つの `journal.md`（＝1セッションディレクトリ）内で常に同じ値なので、ファイル冒頭に1回だけ書きます。

```markdown
# Reader Walk ジャーナル

- **persona_id**: `000_default`
- **session_id**: `20260830_000_default`
```

各場面には、感想本文の後ろへ1行だけの反応行を残します。

```markdown
反応: scene=ch01-003 / intensity=4 / valence=mixed / tags=curiosity,tension / pull=5
```

`intensity` は感情の大きさ、`pull` は次を開きたい強さで、どちらも0〜5です。`valence` は `positive` / `negative` / `mixed` / `neutral`、`tags` は `curiosity` / `tension` / `surprise` / `joy` / `relief` / `sadness` / `anger` / `fear` / `confusion` / `boredom` / `admiration` から1〜3個をカンマ区切り（角括弧・引用符無し）で選び、記載順に並べます。場面アンカーは `<!-- scene: chNN-MMM -->` の形式を使い、本文に無い場合は入力ファイル名と場面出現順から `source_file_stem-sNNN` を決定的に付けます。

ヘッダと反応行の必須項目・順序・値域を検査し、既読範囲の山谷を生成するには、セッションディレクトリを指定して次を実行します。`journal.md` が正本で、trace JSONは同じセッションディレクトリの生成物です。

```bash
python tools/novel_reader_walk_check.py novels/NNN_作品名/_reader/walk/<session_id> \
  --trace-output novels/NNN_作品名/_reader/walk/<session_id>/reaction_trace.json
```

新規の定量化セッションでは終了コード0を確認してから完了します。定量化前の既存エントリを移行中だけは `--allow-missing-reaction` を追加してWARNINGとして扱えますが、ERRORが無いことを確認します。移行前のルート直下journalだけは `--legacy-root` を追加して一時的に検査できます。`rising` / `falling` / `flat` / `peak` は同じセッション・ペルソナ内の既読場面からハーネスが導出します。数値やtraceの内容はチャットには返しません。

---

## Editor Score（深掘り採点）

足切り（First Reader）通過後の作品に使います。「どこを直すと何点上がるか」の優先順位を出します。足切りが済んでいない場合は先に First Reader で判定してください。

### チャットへの指示文

```text
全文をEditor Scoreで採点してください。
```

長文（30,000字超）の場合はあらすじを先行させます（後述「Synopsis」を参照）。

```text
あらすじを作成してから、Editor Scoreで採点してください。
```

### Monogatari Coach が行うこと

`_how_to/editor_score.md` を参照し、以下の5項目100点で採点します。

| 項目 | 配点 |
|------|------|
| 構造・プロット完成度 | 20点 |
| キャラクター深度 | 20点 |
| 文体・文章品質 | 20点 |
| 世界観・設定の一貫性 | 20点 |
| 完成度・磨き | 20点 |

足切り用の配点（6項目）とは別の基準です。混同しないでください。

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/score_YYYYMMDD_HHMM.md`
- チャットには「総合点・致命的弱点件数・保存先パス」のみ返ります。
- 採点後、`_meta.md` の「評価・足切り履歴」節が更新されます。

---

## Consistency Audit（一貫性監査）

複数章が完成した段階で、設定・口調・時系列の矛盾を章横断で洗い出します。点数ではなく表形式で出力します。

### チャットへの指示文

```text
第1〜3章の設定・口調の一貫性を監査してください。
```

### Monogatari Coach が行うこと

`_how_to/consistency_audit.md` を参照し、以下の4観点で全章を横断します。

1. キャラクター一貫性（口調・行動原理・外見）
2. 世界観・設定の一貫性（用語・能力・地理）
3. プロット・時系列の整合（伏線の回収・経過時間）
4. 語句・表記の統一（固有名詞の揺れ・数字表記）

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/consistency_YYYYMMDD.md`
- チャットには「矛盾/要確認/軽微の件数内訳・保存先パス」のみ返ります。

---

## Synopsis（前処理・長文評価用）

G3 全文足切りや Editor Score の前に作成する、評価者向けの客観的なあらすじです。合計30,000字超の作品では先行作成が必須です。

### チャットへの指示文

```text
あらすじを作成してください。
```

または Editor Score と組み合わせて、

```text
あらすじを作成してから、Editor Scoreで採点してください。
```

### Monogatari Coach が行うこと

`_how_to/novel_synopsis_for_review.md` に従い、400字前後の客観的なあらすじを作成します。作者の宣伝語調ではなく、評価に必要な情報（主人公・対立構造・結末・テーマ）を過不足なくまとめます。

### ユーザーが確認できるもの

- 保存先: `novels/<作品>/_reader/synopsis_YYYYMMDD.md`
- チャットには「保存先パスと次に行う評価の案内」だけを返します。

---

## 長文評価パイプライン（30,000字超）

合計30,000字を超える作品の G3 足切りや Editor Score では、多段パイプラインを使います。

### 評価フォルダの構造

```
novels/<作品>/_reader/
  synopsis_YYYYMMDD.md          ← 最終成果物（Step A）
  _work/<YYYYMMDD>/             ← 評価セッションの作業フォルダ
    step_b.md                   ← 構造・プロット中間分析
    step_c.md                   ← 文体・描写中間分析
    ch01_eval.md〜chNN_eval.md  ← 章ごとのスコアノート
    aggregate.md                ← 加重平均計算メモ
  score_YYYYMMDD_HHMM.md        ← 最終成果物（Editor Score）
```

`_reader/` 直下は最終成果物のみです。`_work/<YYYYMMDD>/` の中間ファイルは過程の記録として残します。

### 加重平均の計算式

```
最終総合点 = Σ（章スコア × 章文字数） ÷ 合計文字数
```

章ごとのスコアを文字数で重み付けして合計します。結果は `aggregate.md` に記録します。

### 準備ツールの使い方

評価セッションを始める前に、以下のコマンドで章構成・既存評価・テンプレートを一覧表示できます。

```bash
# 章別文字数・既存評価・frontmatter テンプレを表示する
python tools/novel_evaluation_prepare.py novels/NNN_作品名

# Editor Score 用のテンプレートを表示する
python tools/novel_evaluation_prepare.py novels/NNN_作品名 --mode editor-score
```

---

## 評価スコアの推移を確認する

`_reader/` に複数の評価ファイルが貯まったら、以下のコマンドで推移を確認できます。

```bash
# スコアが付いたファイルのみ（既定）
python tools/novel_evaluation_diff.py novels/NNN_作品名

# Synopsis・Interest Check なども含めて全ファイルを表示
python tools/novel_evaluation_diff.py novels/NNN_作品名 --all
```

清書前後のスコア変化を比較するときは、旧スコアは削除せずに両方残します。`_meta.md` の評価履歴表に「清書前」「清書後」として別行で記録してください。

---

## 評価ファイルの形式を機械チェックする

First Reader の評価ファイルに必須見出しが揃っているかを確認できます。

```bash
# 特定ファイルをチェックする
python tools/novel_slush_gate_lint.py novels/NNN_作品名/_reader/YYYYMMDD_HHMM.md

# 作品フォルダを指定すると最新ファイルを自動選択する
python tools/novel_slush_gate_lint.py novels/NNN_作品名
```

終了コード 0（全通過）/ 1（ERROR あり）/ 2（WARNING あり）で結果を返します。

---

## 査証ログとの違い

`_reader/` は評価本文の保存先です。`_workingspace/log/` は作業事実を残す査証ログなので、書評本文そのものは入れません。

たとえば査証ログには「第2章の G2 足切りを実施し、`_reader/20260608_1300.md` に保存した（75/100・読むべき）」という事実だけを追記します。

---

## 関連ページ

- 指示文の一覧は [指示出しベースのワークフロー](instruction-driven.md) を参照してください。
- 評価ツールの詳細は [ツールリファレンス](../tools/index.md) を参照してください。
- 作品フォルダ内の保存先は [Project Structure](../project-structure/index.md) を参照してください。
