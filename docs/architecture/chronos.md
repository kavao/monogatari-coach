# CHRONOS 技術詳細

## TL;DR

CHRONOS は、小説の「読者に提示される順序」と「世界の中で実際に起きた順序」を YAML で分けて持ち、順序の矛盾を機械的に検出する検査レイヤです。P0 は日付なしの順序制約（`after` / `before`）とルール **CHR001**（時系列の循環）だけを扱います。外部 provider へは接続しません。

## このドキュメントを使う場面

1. **どんな場面で使うか** — 回想・証言・時系列の入れ替えがある作品で、「この出来事は本当はどちらが先か」を資料として残したいとき。執筆のたびに必須ではありません。
2. **チャットへの指示文** — 「CHRONOS を init して」「この作品を chronos check して」と入力すると、Monogatari Coach は作品フォルダの `chronos/` を対象に CLI を実行します。
3. **Monogatari Coach が行うこと** — 雛形の作成、イベント YAML の読み込み、順序グラフの構築、循環の報告。原稿や `world.md` は書き換えません。
4. **ユーザーが確認できるもの** — `novels/<作品>/chronos/` の YAML、コンソールの `ok` または `CHR001` 行、`view --actor` の人物別リスト。

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

問題がなければ `ok: N events, 0 findings` と出ます。循環があると `CHR001 error:` と閉路のイベント ID が出て、終了コードは 1 です。`--json` を付けると機械可読になります。

人物が関与するイベントを、制約順に見ます。循環があるときは CHR001 を標準エラーへ出し、一覧は「順序は信用できない」と注記します。終了コードは 1 です。

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

## P0 でやらないこと

- 絶対時刻の窓計算（STN）、年齢・移動可能性（CHR002 / CHR003）
- 知識・伏線（CHR004 以降）
- 原稿からの自動抽出。再抽出が作者編集を壊さない承認フローは P3 です
- 執筆完了の自動ゲート。METRON の本文計測ともまだ自動接続しません
- `chronos watch` と `.cache/resolved.json`（P1）

METRON と並べて常用すると起動コストが乗ります。P0 は章単位 YAML と決定的 lint に留めています。1,000 件規模の読み込みが遅ければ、P1 の JSON キャッシュと常駐 `watch` を前倒しします。

## 開発上の入口

正規の実行入口は `python tools/chronos_cli.py` です。パッケージは `tools/chronos/` です。認証情報は読みません。
