# CHRONOS 技術詳細

## TL;DR

CHRONOS は、小説の「読者に提示される順序」と「世界の中で実際に起きた順序」を YAML で分けて持ち、順序の矛盾を機械的に検出する検査レイヤです。P0 は日付なしの順序制約（`after` / `before`）とルール **CHR001**（時系列の循環）を扱います。作品が次元を宣言した場合だけ、人物状態（P0.5、CHR010〜013）も畳み込み検査します。外部 provider へは接続しません。

## このドキュメントを使う場面

1. **どんな場面で使うか** — 回想・証言・時系列の入れ替えがある作品で、「この出来事は本当はどちらが先か」を資料として残したいとき。執筆のたびに必須ではありません。
2. **チャットへの指示文** — 「CHRONOS を init して」「この作品を chronos check して」と入力すると、Monogatari Coach は作品フォルダの `chronos/` を対象に CLI を実行します。
3. **Monogatari Coach が行うこと** — 雛形の作成、イベント YAML の読み込み、順序グラフの構築、循環と（宣言がある作品では）人物状態の報告。原稿、`world.md`、挿絵 YAML は書き換えません。
4. **ユーザーが確認できるもの** — `novels/<作品>/chronos/` の YAML、コンソールの `ok` または `CHR001` / `CHR010` 行、`view --actor` の人物別リストと（状態を使う作品では）前後の次元値。

## 保存場所

作品フォルダ直下の `chronos/` が正本です。データベースは使いません。

```text
novels/<作品>/chronos/
  events/
    ch01.yaml          # 章単位で複数イベント
    unplaced.yaml      # まだ章に紐付かないもの
  entities/
    characters.yaml
    locations.yaml
  scenes.yaml
  chronos.config.yaml
  .cache/              # P1 以降の導出物。削除可
```

イベントは 1 件 1 ファイルにせず、章ファイルへまとめます。ID（`EVT-0001` など）はファイル位置と独立です。シーン ID は METRON と同じ `chNN-MMM` か、計画書形式の `SCN-0302` のどちらかを使えます。

必須フィールドはイベントの `id` と `title` だけです。日付は書いてなくても検査できます。

## 作品単位の有効化

作品ごとに CHRONOS の自動ワークフローを使う場合は、作品の `config.md` の「## 基本情報」表に次の行を追加します。

```markdown
| CHRONOS | ON |
```

新規作品の初回作成は `python tools/novel_onboard.py` を入口にします。作成時に確認への返答がない場合は「未応答・既定 ON」として行と `chronos/` を記録・準備します。既存作品の行なしは従来どおり OFF です。

行なしまたは `OFF` なら、自動ワークフローは CHRONOS の `init` / `check` を行いません。`ON` で `chronos/` が無い場合は `未登録` として本文保存と分けて報告します。当該章のイベント手入力は推奨ですが、本文や執筆完了の必須条件ではありません。明示的に `chronos_cli.py` を実行した場合は、このフラグを理由に拒否しません。

フラグの値は `ON` / `OFF` のみです。未知値・重複キー・既存 `config.md` の読込失敗は設定エラーとして扱います。P0 は日付なしの順序制約と循環検出 `CHR001` に限り、原稿からの自動抽出は行いません。人物状態は別途 `character_state.dimensions` を書いた作品だけ有効です。

## 操作

作品フォルダへ雛形を置く前に、作成予定のパスだけを確認します。`--dry-run` ではファイルを書きません。

```bash
# 確認（dry-run）— 作成予定の chronos/ パスを表示する
python tools/chronos_cli.py init novels/NNN_作品名 --dry-run

# 本番 — 空の chronos/ を作成する。既にある場合は失敗する
python tools/chronos_cli.py init novels/NNN_作品名
```

実行後、`novels/NNN_作品名/chronos/` に設定と空のイベントファイルができます。

順序の矛盾を検査します。LLM は呼びません。

```bash
python tools/chronos_cli.py check novels/NNN_作品名
```

問題がなければ `ok: N events, 0 findings` と出ます。循環があると `CHR001 error:` と閉路のイベント ID が出て、終了コードは 1 です。状態を使う作品では CHR010〜013 も同じ形式で出ます。入力エラー（未知参照など）は終了コード 2 です。warning / info だけのときは終了コード 0 です。`--json` を付けると機械可読になります。

人物が関与するイベントを、制約順に見ます。循環があるときは CHR001 を標準エラーへ出し、一覧は「順序は信用できない」と注記します。終了コードは 1 です。状態を使う作品で `--actor` を付けると、各イベントの `before` / `after` を表示します。未確定順序や循環では状態を捏造せず、未解決理由を注記します。

```bash
python tools/chronos_cli.py view novels/NNN_作品名 --actor CHR-protagonist
python tools/chronos_cli.py view novels/NNN_作品名 --location LOC-lab
```

## イベントの書き方

```yaml
events:
  - id: EVT-0001
    title: 研究所事故
    actors: [CHR-father]
    location: LOC-lab
    time:
      after: [EVT-0000]
      before: [EVT-0004]
```

`time.earliest` / `time.latest` は持っておけますが、P0 の判定には使いません。誤検知を黙らせるときは、理由付きの抑制だけをイベントに書きます。理由のない抑制は受け付けません。

```yaml
chronos:
  ignore:
    - rule: CHR001
      reason: 意図した循環語り
```

## 人物状態（P0.5）

次元を宣言しない作品は、これまでどおり順序検査だけです。`init` 雛形も次元なしです。使う作品だけ `chronos/chronos.config.yaml` に書きます。

```yaml
schema: 1
rules:
  CHR012: warning          # 省略時は OFF。挿絵照合は opt-in
character_state:
  dimensions:
    outfit:
      type: enum
      values: [home, school, travel]
      default: home
      canon: illustration    # または world / text
    present:
      type: bool
      default: true
      canon: world
    whereabouts:
      type: loc_ref
      canon: world
  transitions:
    - dimension: outfit
      from: home
      to: school
  illustration_bind:
    - actor: CHR-a
      character_id: actor_a
      dimension: outfit
      value: school
      variant_ids: [002_school]
    - actor: CHR-a
      character_id: actor_a
      dimension: outfit
      value: home
      variant_ids: [001_normal]
    - actor: CHR-a
      character_id: actor_a
      dimension: outfit
      value: travel
      variant_ids: [003_travel]
```

エンジンは `enum` / `bool` / `loc_ref` の型だけを知ります。次元名と値の意味は作品が付けます。コアにジャンル語は置きません。

イベントは差分だけを書きます。省略した次元は前の値を引き継ぎます。

```yaml
effects_on:
  CHR-a:
    outfit: school
```

初期値は `entities/characters.yaml` の `initial_state` です。未記入は次元の `default`、それもなければ内部値 `unknown` です。YAML で null は書けません。

`loc_ref` は1次元までです。イベントの `location` は参加人物の所在観測になり、登録済みの `LOC-*` である必要があります。明示差分と食い違うと CHR011（warning 既定）になります。観測による変更も遷移表があれば CHR010 の対象です。

同一人物のイベントが `after` / `before` などで前後を比較できないときは CHR013（error 既定）です。その人物の状態は解決しません。グラフに循環があれば、CHR001 を抑制していても状態解決全体を止めます。

挿絵照合（CHR012）は `rules.CHR012` を warning / error / info にし、かつ `illustration_bind` があるときだけ走ります。照合する次元は enum かつ `canon: illustration` です。イベントの `source.illustrations` は作品ルート相対で `illustrations/pages/` 配下の YAML に限ります。無効時は挿絵やタグファイルを読みません。

追加フィールドは省略できます。古い `schema: 1` の YAML はそのまま読めます。新しいキーを含むファイルは、更新前のバイナリでは読めません。check / view は読取専用です。

## P0 でやらないこと

- 絶対時刻の窓計算（STN）、年齢・移動可能性（CHR002 / CHR003）
- 知識グラフ（CHR004 以降）。最初の知識は作品の bool 次元で足ります
- 原稿からの自動抽出。再抽出が作者編集を壊さない承認フローは P3 です
- 執筆完了の自動ゲート。`chronos check` は METRON の本文計測を呼びません。執筆工程への接続は [Writing bridge](writing-bridge.md) が行います
- `chronos watch` と `.cache/resolved.json`（P1 の日付窓）
- コアへのジャンル語の埋め込み。次元名と値は作品 YAML に閉じます

METRON と並べて常用すると起動コストが乗ります。P0 は章単位 YAML と決定的 lint に留めています。1,000 件規模の読み込みが遅ければ、P1 の JSON キャッシュと常駐 `watch` を前倒しします。

## 開発上の入口

正規の実行入口は `python tools/chronos_cli.py` です。パッケージは `tools/chronos/` です。認証情報は読みません。
