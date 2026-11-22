# 作業計画

このフォルダは、Monogatari Coach 全体の作業予定・作業計画・中長期の着手順を置く場所です。

## 使い分け

- `_workingspace/plans/`: これから行う横断的な予定、月次・週次・セッション単位の作業計画
- `_workingspace/log/YYYYMM.md`: 実施済み作業の査証ログ
- `_workingspace/diary/YYYYMM.md`: 作品を横断する判断理由、運用知見、次回以降も効く学び
- `novels/<作品>/_meta.md`: 作品ごとの進捗、伏線、次回タスク、外部投稿用情報

## ファイル命名（必須）

トピック別の作業計画（チェックリスト付きの単発・中長期計画）は、**行頭に作成日 `YYYYMMDD` とアンダースコア**を付ける。

| 形式 | 例 | 用途 |
|------|-----|------|
| **`YYYYMMDD_<slug>.md`** | `20260620_illustration-plan-and-ir-workflow.md` | トピック計画（**新規作成時は必須**） |
| **`YYYYMM.md`** | `202606.md` | 月次の作業予定（日付プレフィックス不要） |
| **`backlog.md`** | 固定名 | 未着手候補の集約 |
| **`README.md`** | 固定名 | 本フォルダの案内 |

- `<slug>` は英小文字・ハイフン・アンダースコア（日本語ファイル名は使わない）。
- **作成日**はファイルを **最初に置いた日**（計画の着手日）。後から大幅改訂してもファイル名の日付は原則変えない。
- 既存の `YYYYMM_<slug>.md`（例: `202605_hair_tag_workflow.md`）はレガシー。**新規は `YYYYMMDD_` 8桁**に統一する。

## 状態（ファイル内の先頭）

計画ファイルは**場所を動かさない**。完了フォルダへ移さない。ファイル名の先頭にも印を付けない。

見出しの直後に、次の1行を置く。

`状態: 計画案`

詳細があるときは全角括弧に続ける（`状態: 計画案（P0 の確認待ち）`）。先頭の語は次の6つのどれかだけにする。

| 語 | 未完了か | 意味 |
|---|---|---|
| **計画案** | 未完了 | 仕様または実装がまだ始まっていない |
| **進行中** | 未完了 | 実装が始まっている |
| **保留** | 未完了 | 作者の判断で止めている。後日 |
| **実装済み** | 完了側 | 正本は入った。任意の残り・追随・実作品適用だけ |
| **完了** | 完了側 | この計画の目的を達した |
| **閉じた** | 完了側 | 後継へ引き継いだ、やらないと決めた、月次の過去 |

未完了の拾い方は、`状態: 計画案` / `進行中` / `保留` で検索する。2026-11-22 時点の未完了は下の「未完了」節。以降は各ファイルの `状態:` が正である。作品固有の起こし計画だけ、作品フォルダへ移してよい。

## 推奨ファイル

- `YYYYMM.md`: 月次の作業予定
- `backlog.md`: 未着手候補、いつか扱いたい改善案
- `session.md`: 直近セッションで進める短期計画（置く場合も `YYYYMMDD_session.md` 推奨）

## タスク運用

- プロジェクト構築、資料展開、新規作品作成など複数段階の作業では、残作業をチェックリストとして書き出します。
- セッション終了時や区切りごとに、未完了タスクから次に進めるべき作業を確認します。計画全体の進みは先頭の `状態:` で見る。
- タスクが完了したら、該当行を `- [x]` に変更し、必要に応じて完了日・関連ファイル・査証ログ記録済みであることを短く添えます。計画の区切りが変わったら `状態:` の語も更新する。
- 完了したタスクは原則としてすぐ削除せず、作業の流れが読めるように残します。長くなりすぎた場合のみ、同じファイル内の「完了」欄や月次アーカイブへ移します。
- `_workingspace/plans/` は現在と未来の作業に加え、完了までの流れを見通す場所です。過去の厳密な保証は `_workingspace/log/YYYYMM.md` に任せます。

計画を実行したら、実施済みの事実は必ず `_workingspace/log/YYYYMM.md` に査証ログとして残します。

## 未完了（2026-11-22 分類）

この表は一括分類の控えである。進んだら該当ファイルの `状態:` を直し、必要ならこの表も直す。

### 計画案

| ファイル | 内容 |
|---|---|
| [20261122_novel-compare-branch.md](20261122_novel-compare-branch.md) | 改訂版のための作品分岐 |
| [20261122_temporary-file-retention.md](20261122_temporary-file-retention.md) | 一時ファイルの保存期限 |
| [20261121_metron-length-relaxation.md](20261121_metron-length-relaxation.md) | METRON の分量判定を清書へ |
| [20261121_expression-mix-weights.md](20261121_expression-mix-weights.md) | 表現ミックスの重み採用 |
| [20261114_model-adaptive-writing-support.md](20261114_model-adaptive-writing-support.md) | モデルに応じた執筆補助 |
| [20261114_prose-readability-138-139.md](20261114_prose-readability-138-139.md) | 138 と 139 の読みごたえ比較 |
| [20260926_ethos-tool-integration.md](20260926_ethos-tool-integration.md) | ETHOS の検証・執筆連携 |
| [20260922_novelai-manga-quality-lettering.md](20260922_novelai-manga-quality-lettering.md) | NovelAI 漫画の写植品質 |
| [backlog.md](backlog.md) | character.md lint とタグ 000/100 の Phase 2 |

### 進行中

| ファイル | 内容 |
|---|---|
| [20261025_showing-axes.md](20261025_showing-axes.md) | 見せ方軸の P4 書き比べ |
| [20261020_goal-mode-optimization.md](20261020_goal-mode-optimization.md) | goal モード C1 の再試行 |
| [20261018_design-to-text-chapter1.md](20261018_design-to-text-chapter1.md) | 設計から第1章を起こす Phase 6 |
| [20261009_ai_writer_creative_exploration.md](20261009_ai_writer_creative_exploration.md) | AI Writer 探索 E2 |
| [20261008_novelai_novel.md](20261008_novelai_novel.md) | NovelAI テキスト執筆基盤 Phase 1 |
| [20260930_manga-panel-assembly-psd.md](20260930_manga-panel-assembly-psd.md) | コマの PSD 組み立て（ブランチ統合） |
| [20260929_manga-panel-layout-rhythma.md](20260929_manga-panel-layout-rhythma.md) | コマ割り S6 |
| [20260912_design-spec-story-sync.md](20260912_design-spec-story-sync.md) | 本文変更の出来事同期 Phase 3 |
| [20260725_publishing-cover-outputa.md](20260725_publishing-cover-outputa.md) | 出版表紙 C2 / C3 |
| [20260721_publishing-package-phase1.md](20260721_publishing-package-phase1.md) | 出版パッケージ（電子版許諾） |

### 保留

| ファイル | 内容 |
|---|---|
| [20261025_chronos-off-redesign.md](20261025_chronos-off-redesign.md) | CHRONOS 再設計 |
| [20261024_work-folder-layout.md](20261024_work-folder-layout.md) | 残る実作品の `_meta` 移行 |
| [20261024_grok-subagent.md](20261024_grok-subagent.md) | Grok をサブエージェントに |
| [20260915_manga-page-yaml-builder.md](20260915_manga-page-yaml-builder.md) | 漫画 YAML 量産ビルダー |
| [20260913_novel-110-metron-missed-start.md](20260913_novel-110-metron-missed-start.md) | 小説110 の METRON 後追い |
| [20260902_chronos.md](20260902_chronos.md) | CHRONOS P1（休止中） |
| [20260722_publishing-package-phase2.md](20260722_publishing-package-phase2.md) | 紙書籍の最終入稿カバー |
| [202605_tag_two_tier_variants.md](202605_tag_two_tier_variants.md) | タグ 000/100 番台 Phase 2 |

`実装済み` は完了側とする。任意の残り（実作品未適用、既存 `_meta` 未変換など）は各ファイルの括弧を見る。
