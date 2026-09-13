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

## 作品単位の有効化

作品ごとに METRON の自動ワークフローを使う場合は、作品の `config.md` の「## 基本情報」表に次の行を追加します。

```markdown
| METRON | ON |
```

新規作品の初回作成は `python tools/novel_onboard.py` を入口にします。作成時に確認への返答がない場合は「未応答・既定 ON」として行と `_metron/` を記録・準備します。既存作品の行なしは従来どおり OFF です。

行なしまたは `OFF` なら、自動ワークフローは METRON の成果物作成・計測を行いません。`ON` でも本文保存の完了ゲートにはならず、契約・Beat・マーカー不足や CLI 失敗は `未計測／要対応` として本文保存と分けて報告します。明示的に `metron_cli.py` を実行した場合は、このフラグを理由に拒否しません。

フラグの値は `ON` / `OFF` のみです。未知値・重複キー・既存 `config.md` の読込失敗は設定エラーとして扱います。V1 の Deepen / 再生成や provider 呼び出しは、承認済み設定とユーザー承認が別途必要です。執筆工程への接続は [Writing bridge の局所修復と本文反映](writing-bridge.md) です。`chronos check` や `metron_cli.py analyze` を同じ本文版へ重ねません。

## 計測と判定

本文は NFC に正規化し、Beat マーカーを除去した本文上のコードポイント半開区間として `spans` に記録します。`Beat coverage` は BeatPlan の全 ID に正しい開閉マーカーのスパンが 1 件ずつある状態です。

`scene.overall_budget_ratio` は `scene.chars / Σ(beat.chars_hint)` です。`head_tail_ratio` は先頭 2 Beat と末尾 2 Beat の密度比で、4 Beat 未満または先頭群ゼロの場合は算出しません。

V1 の自動修復候補は次のクラスです。

- `BeatMissing`: マーカー・スパンの欠落、またはモデル別のスパン下限未達（単独再生成。極端な短さだけ）
- `BeatThin`: 段落数・会話往復数と、段落・会話充足率の構造予算未達。計画下限未達だけ Deepen します。校正典型値だけの未達は指摘を残し、自動修復しません。文字数比とは別統計です
- `TooShort`: シーンが `chars_floor` 未満、または Beat が `chars_hint` 未満（Deepen のみ。末尾再生成には使わない）
- `EndingRush`: 末尾密度比のモデル別閾値未達（末尾 Beat の単独再生成）

分量バーは構造バーと別に置きます。シーンの床は `generation.chars_floor`（既定 4000字）、Beat の床は `chars_hint` です。未達は `TooShort` になり、出来事を変えずにニュアンスを深める Deepen だけで自動修復します。末尾の再生成には使いません。Writer / Deepen への字数指示は床以上の指示目標です（既定 1.4 倍。シーン床 4000 字なら 5600 字。床 1 字では丸めで 1 字のままです）。水増しは禁止します。深化の対象は手順・制度・選択に加え、感情の変化と身体の変化、感覚・内面・会話です。すでに書いた内容の言い換えは対象にしません。執筆接続の `context.md` は、この下限と指示目標を人間が読める形で出します。指示目標は助言であり、未達だけでは検査を止めません。既存の作業 run は新しい `prepare` が必要です。

`GenerationTruncated` は従来どおり自動修復しません。欠落Beatがあっても `regenerate` や Deepen へ進めません。感覚描写・内面描写・要約標識は補助指標であり、V1 の `BeatThin` の単独根拠にはしません。減衰キャリブレーションの `too_short_ratio` はシーン合格線に使いません。

## V1 の修復境界

`classify.py` は `config/metron_models.yaml` の `calibrated: true` かつ必要な値が揃ったモデル設定だけを受け入れます。`granularity: auto` は Beat の `chars_hint` 合計が `reliable_span_chars` を超えた場合に Beat 単位へ切り替えます。`isolated`、heavy Beat、末尾 hook は独立コールとして計画します。

provider 呼び出しは `repair_scene()` のコールバックへ注入します。Expand は同一 Beat につき最大 2 回で、`expand_retention_threshold` 未満の元文残存率、元本文と同一の候補、文字数が増えていない候補、新規文が既存文または同一候補内の他の新規文と高類似の候補は棄却して著者提示へエスカレーションします。類似度は句読点を除いた文字 2-gram の Jaccard で、短い反応文は対象外です。結合校正は最大 1 回で、短縮・元文の文の削除・Beat 順の入れ替え・事象変更を許容しません。Beat マーカーを保持して校正し、同一の冒頭文が新たに反復された場合も機械的に棄却します。再計測は正規化済みの最終本文と一致するマーカー付き稿で行います。シーンが `chars_floor` 未満のときは、必須の下限未達を先に直し、追加候補だけ飽和していない Beat へ寄せます。適格が無く必須修復も無いときは結合校正も出さず、`__scene_floor__` で止めます。`FINAL.md` へ保存する本文からは Beat / fact コメントを除去し、連続した空行は場面転換用の1行までに正規化します。既存の `FINAL.md` は上書きしません。

## 開発上の入口

正規の実行入口は `python tools/metron_cli.py` です。CLI は契約検証、計測、レポート、ローカル fixture のキャリブレーション集計、V1 判定、生成コール計画、マーカー除去済み FINAL 保存を提供します。実測生成や provider の認証情報は CLI の暗黙動作にしません。
