R2 の job 形。context_hash / prompt_hash は実装時に実送信文字列から計算する。
regenerate の同一 Beat 上限は 1。deepen は 2。R1 では実行しない。

Phase 2 の終了状態（実装済み。静的フォルダではなく回帰テストが正）:

- E: 床到達 fixture で advisory `TooShort` だけ。inspect 終了コード 0。`status` / `report.md` は `required_findings: none` と advisory を分ける。`metron_auto_repair: none`。C1 が success / skipped かつ repair 非 active のときだけ次手は `床到達・必須なし → 保存へ`。C1 未確認と修復中は案内しない。`repair-begin` は `REPAIR_NOT_NEEDED`。
- C: 短文かつ高密度の**保存予定全文**。`publish --dry-run` は終了コード 1。対象ファイルが無い／旧バイトのまま。`publish_state` と backup は作らない。`refine` / `append` で候補 pass・全文 fail なら dry-run が止まる。本番 `publish` は書いてから結合後全文の句読点 fail を記録する。
- D: `locate-quote` は正規化本文の一意 quote だけ `start` / `end` / `range_sha256` / `text_sha256` を返す。inspect と同じ座標と stale 検証。0 箇所は `UNKNOWN_REF`。2 箇所以上は `JOB_CONFLICT`。改変・欠落候補と正本変更は `STALE_EVIDENCE`。
