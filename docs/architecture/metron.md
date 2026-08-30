# METRON 技術詳細

## TL;DR

METRON は、Scene を Beat に分けて本文の密度と構造予算を計測し、必要な Beat だけを局所修復する検査レイヤです。V0 はマーカー付き本文の計測とレポート、V1 は承認済みモデル設定に基づく失敗分類・生成単位計画・Expand を扱います。外部 provider への接続はこのモジュールの責務ではありません。

## 保存単位

Scene ごとの成果物は、本文アンカーと同じ `scene_id` を使って次へ保存します。

```text
novels/<作品>/_metron/<scene_id>/
  contract.yaml
  beats.yaml
  draft.NNN.md
  spans.NNN.yaml
  metrics.NNN.yaml
  regression.NNN.yaml
  report.NNN.md
  FINAL.md
config/metron_models.yaml
```

`SceneContract`、`BeatPlan`、`Spans`、`Metrics` は Pydantic v2 のモデルを実行時の正とし、YAML は保存形式として扱います。`scene.id` は `chNN-MMM` 形式で、`_metron/<scene_id>/` と一致させます。V0 では `chronos_span` を省略できます。

## 計測と判定

本文は NFC に正規化し、Beat マーカーを除去した本文上のコードポイント半開区間として `spans` に記録します。`Beat coverage` は BeatPlan の全 ID に正しい開閉マーカーのスパンが 1 件ずつある状態です。

`scene.overall_budget_ratio` は `scene.chars / Σ(beat.chars_hint)` です。`head_tail_ratio` は先頭 2 Beat と末尾 2 Beat の密度比で、4 Beat 未満または先頭群ゼロの場合は算出しません。

V1 の自動修復候補は次の 3 クラスです。

- `BeatMissing`: マーカー・スパンの欠落、またはモデル別のスパン下限未達
- `BeatThin`: `budget_ratio`、段落数、会話往復数の構造予算未達
- `EndingRush`: 末尾密度比のモデル別閾値未達

`TooShort` は coverage 充足時の総量不足を報告するだけで、`GenerationTruncated` と同様に自動修復しません。感覚描写・内面描写・要約標識は補助指標であり、V1 の `BeatThin` の単独根拠にはしません。

## V1 の修復境界

`classify.py` は `config/metron_models.yaml` の `calibrated: true` かつ必要な値が揃ったモデル設定だけを受け入れます。`granularity: auto` は Beat の `chars_hint` 合計が `reliable_span_chars` を超えた場合に Beat 単位へ切り替えます。`isolated`、heavy Beat、末尾 hook は独立コールとして計画します。

provider 呼び出しは `repair_scene()` のコールバックへ注入します。Expand は同一 Beat につき最大 2 回で、`expand_retention_threshold` 未満の元文残存率なら候補を棄却して著者提示へエスカレーションします。結合校正は最大 1 回で、短縮・元文の文の削除・事象変更を許容しません。Beat マーカーを保持して校正し、同一の冒頭文が新たに反復された場合も機械的に棄却してから再計測します。`FINAL.md` へ保存する本文からは Beat / fact コメントを除去し、既存の `FINAL.md` は上書きしません。

## 開発上の入口

正規の実行入口は `python tools/metron_cli.py` です。CLI は契約検証、計測、レポート、ローカル fixture のキャリブレーション集計、V1 判定、生成コール計画、マーカー除去済み FINAL 保存を提供します。実測生成や provider の認証情報は CLI の暗黙動作にしません。
