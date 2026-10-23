---
targets: ["*"]
description: "Monogatari Coach の常時適用する最小概念正本"
globs: [".rulesync/**", "tools/**", "docs/**", "_workingspace/**", "rulesync.jsonc", "sync_rules.py", "readme.md"]
---

# 概念正本

このファイルは全作業に必要な最小の判断だけを置く。作品・画像・出版の詳細は [ワークフロー詳細仕様](workflow-specification.md) と該当スキルを正とする。

## Python 実行

- `uv run python` で実行する（Windows の素の `python` はストア用スタブになりうる）。初回は `uv sync` → `uv run python howto_init.py`。

## 正本と副本

- ルール・スキルの正本は `.rulesync/rules/` と `.rulesync/skills/`、`AGENTS.md` / `CLAUDE.md` は生成物である。
- 創作技法の雛形は `_how_to.example/`、`_how_to/` はユーザー調整領域である。
- 操作説明は `docs/`、チャットは要約である。
- 小説本文は `novels/<作品>/_novel_text/novel_text*.md`、キャラクタータグは `tag/characters/*.yaml`、漫画ページは `manga/pages/*.yaml`、挿絵ページは `illustrations/pages/*.yaml` を正本とする。
- 正本を更新できる場合、副本だけを直して完了扱いにしない。生成物を変えたいときは先に正本を変え、再生成する。
- 漫画の後載せ写植はページYAMLの `manga.lettering` を基本スタイル正本とする。既定は縦書き・基準サイズ30・矩形中央寄せ・必要時のみ縮小。個別 `writing_direction` は明示時だけ上書き。縦書き約物は縦組み字形へ変換するが `？` は通常字形のまま（IR本文は不変）。
- 漫画ページの吹き出しはページ生成時に描く。標準は写植なし。後載せと NovelAI の T1 割り当ては `workflow-specification.md`「漫画ページの吹き出し描画」「漫画写植の作品メタ」。既定 provider `grok_pro`。操作は `docs/image-generation/manga-page-edit.md`。

## 完了扱い条件

- ファイル成果物は、正しい正本パスへの書込み後に再読込または対応する検証で確認してから完了と報告する。
- 画像生成は、ユーザー承認後の本番実行と指定保存先での実ファイル確認を満たしてから完了とする。キャラクタータグ一括は、承認前のチャットに dry-run のプレビューと Python コマンドを書く。詳細手順は `workflow-specification.md` を正とする。
- 文字数を報告・記録するときは `tools/novel_char_count.py` の集計値を使う。
- 章別実文字数の一覧を置くときは `_meta.md` I.1「章別文字数」を正本とする。数値は `novel_char_count.py`。設計書の想定尺は目標であり在庫ではない。
- 小説本文の初稿・場面追記は、対象ファイルに対する `tools/novel_punctuation_metrics.py --gate` が成功してから完了とする。`writing_bridge` の `publish --dry-run` が句読点 fail なら正本を書かない。本番 `publish` 後は `report.json` の句読点記録を正とし、失敗でも本文は戻さない。未達なら完了報告しない。
- 小説本文の執筆・清書完了は、対象章を一意に解決したうえで `design_specification.md` の確定出来事を突き合わせ、`_meta.md` に `更新` / `差分なし` / `未完了` の証跡を残してから報告する。解決不能と書込失敗は完了としない。手順はスキル `novel-story-reflection`。
- METRON / CHRONOS ON の本文を保存したときは、完了報告に **`計測済み` / `未計測`** を必ず明記する。`_writing/` に run 証跡が無い本文は未計測として扱い、未計測のまま完了報告した章では後続章へ進まない。未計測の保存と完了は両立しない。
- ユーザーが第X章だけを指定したときは1章で停止する。第X〜Y章の明示範囲または複数章の列挙は各章を1章ずつ直列に完了させ、指定終端で停止する。失敗・stale・escalated・ユーザー停止では後続章へ進まない。
- 作業事実は `_workingspace/log/YYYYMM.md` へ追記し、次回以降も使う判断理由は `_workingspace/diary/YYYYMM.md` へ追記する。対象作品の config.md に `AUDIT_LOG | OFF` があるときは査証ログを追記しない。
- 新規の漫画ページ `manga/pages/*.yaml` は `schema_version: "1.1"` で作り、`layout_geometry`（コマ数と一致する矩形）と `render_instruction.text_mode`（`generate` / `letter_later` / `none`）を省略しない。欠けていれば作成完了としない。既存 1.0 は読み取り互換で残し、1.1 の欄を足すときは `tools/novel_manga_ir_migrate.py` で先に移行する（移行は矩形と `text_mode` を書かない）。
- 読み進み（Reader Walk）は作品評価を採点せず、既読範囲の感想を `_reader/walk/<session_id>/journal.md` へ追記し、同じセッションディレクトリの `state.md` を更新してから完了とする。定量化を有効にした場合だけ、評価点ではないペルソナ反応メタデータを同じ `journal.md` に残し、完了前に `tools/novel_reader_walk_check.py` で検証する。未読を先読みしない。`walk/` 直下の旧形式は移行時だけ扱う。

## Consistency Audit

- モードは一つ、スコープは `design`（設定3点どうし）と `text`（本文と設定・章横断）の二つ。点数は付けず、足切りを前提にしない。
- `design` は企画 Gate B の B4.5 で必ず実行する。Gate B の外では、Editor Score と `text` 監査の開始時に `tools/novel_audit_freshness.py check` が未監査を返したときだけ、評価の前に自動で1回実行して評価へ戻る。`text` は自動実行しない。
- 本文が無い作品の B4.5 を除き、監査の指摘で資料や本文を直さない。要確認は常に直さずユーザーへ返す。
- 保存は `_reader/consistency_<scope>_YYYYMMDD_HHMM.md`。`tools/novel_consistency_audit_lint.py` が終了コード 0（冒頭の件数と指摘表が一致）を返し、`_meta.md` 評価履歴へ `Consistency Audit (design|text)` 行を追記してから完了とする。完了印は「監査済み」とし、「検査済み」「計測済み」を使わない。執筆完了・publish の条件にしない。詳細は `workflow-specification.md`「Consistency Audit Mode」とスキル `novel-evaluation-output`。

## 設計層と提示層

- 利用者が読んで否定する出力（チャットで出す物語案・あらすじ・候補案・選択肢、`proposal.md` のログライン・あらすじ・キャラクター紹介の欄、本文）を**提示層**、型名・ジャンル葉の名前・ID・決定表・理論名・構造の説明を**設計層**とする。設計層は `_meta.md`・`design_specification.md`・評価や監査のファイルに置く。
- `design_specification.md` の章構成は設計層の置き場だが、各番号の本文は提示層と同じ「誰が何をした」文で書く。型名・深度は見出しに置く。
- 提示層に設計層の語彙を書かない。型名・IDに加え、葉のあだ名・手順の短縮（カタログ短縮）も含む。`character.md` / `world.md` の欄名は設計層、欄の右の説明文は提示層と同じ口語にする。設計の決定は、提示層では具体的な人物・出来事・選択として書く。型名を伏せただけの抽象（「立場の逆転を軸にした成長の物語」）、作品の意図を外から説明する文（「本作は〜を描く」）、設計上の位置の実況（「ここで第一の転換点」）、選択の保留（「〜か、あるいは〜」）は翻訳とみなさない。
- 設計層は利用者が求めたときだけ、提示層とは別の枠で見せる。作業報告（Gate B 完了報告など）は提示層ではないが、設計の情報は案・あらすじと別の節に分ける。利用者の否定は話の言葉のまま受け、内部で設計の決定に対応づける。
- 評価系（下読み・Editor Score・一貫性監査・読み進み）は対象外。書き方の基準は `_how_to.example/synopsis_presentation.md`、適用手順はスキル `novel-planning`（B4 の口語化を含む） / `novel-chat-mode`。

## 文章の伸縮（清書・規定量調整）

- 清書と規定量調整（目標字数への伸縮）は、物語で起きたこと（出来事・所持品・情報の授受・関係・心境の変化・過去・因果）を追加・変更・削除しない。足す・ひねるのは加筆工程、削るのは改稿工程で、どちらもユーザー承認を要する。表現（言い回し・意図しない重複）は清書で削ってよく、清書は多くの場合字数が減る。減らすのは清書前の字数の 10% まで（ユーザー指定があればその割合）で、床を削ってよい目標にしない。意図した繰り返しは残す。削減上限に達しても冗長を残して字数を守らない。残りの候補と子エピソード案を出し、承認後に追加削減してから加筆工程で足す。章の目標字数・場面の床を下回った分も言い換えで埋め戻さず、承認後の加筆工程で足す。
- ユーザーの字数は清書後の仕上がり目標とし、規定量調整は余地を足して増やし、続けて清書する。許容帯に入ったら止め、増減を往復しない。許容帯と床が両立しない設定は受け付けず、床未達は完了にしない。届かなければ不足・超過を報告して止める。
- 増量と欠落 Beat の埋めは機械検査（場面単位の語句反復の棄却を含む）で採用し、JOB ごとに承認を求めない。引き締め・収束・契約修正は著者が事実の欠落・変更の無いことを確かめて採用する（CANON 検査で代えるのは開始時の明示時だけ）。イベント照合はエージェントが行い、矛盾の疑いがあるときだけ尋ねる。著者への確認は保存前の主要な変化の報告1回にまとめる。清書は作業者が旧版と比べて確かめる。
- 反映は、両方 OFF は旧版退避のうえ直接更新、両方 ON は `refine` run の `repair-begin --intent length` と `publish` だけ。手順は `workflow-specification.md`、技法は `_how_to.example/length_ops.md`。
- 執筆の分量は出来事の数で用意し、Deepen は少量の不足（余地込みの目標に対して 10% 未満）だけに使う。章の目標字数があれば書く前に設計密度（`tools/design_density.py`）を見て、少なすぎれば承認を得て設計へ子エピソードを足してから書く。詳細は `length_ops.md` §4.7。

## METRON V1 修復不変条件

- `BeatMissing` と `BeatThin` は別の統計と閾値で判定する。`BeatThin` の自動修復は計画の段落・会話の下限未達に限る。
- 分量の床（場面 `generation.chars_floor`・Beat `chars_hint`）は構造バーと別に置き、床未達（`TooShort`）は出来事を変えない Deepen だけで直す。末尾再生成には使わない。
- Deepen は出来事・結末・視点を変えず、新しい出来事・選択・事実を足さない。元文残存率未達・同一・非増加・同義反復・場面単位の語句反復の候補は適用しない。同一 Beat の試行は2回まで。
- 結合校正は最大1回で Beat 順を変えない。既存の `FINAL.md` は上書きしない。詳細は `workflow-specification.md`「METRON V1 修復不変条件の詳細」。

## CHRONOS P0 不変条件

- 時刻は制約で、日付は任意。検査は決定的コードで行い、LLM に判定を委ねない。`chronos check` は provider を呼ばず、原稿を読まず、書き換えない。
- 抽出候補は承認まで `events/` に入れない。執筆完了ゲートにしない。詳細は `workflow-specification.md`「CHRONOS P0 不変条件の詳細」。

## CHRONOS 人物状態（P0.5）

- 作品が `character_state.dimensions` で `enum` / `bool` / `loc_ref` を宣言したときだけ状態検査が有効になる。コアはジャンル語を持たない。
- 循環または同一人物の未確定順序では状態を捏造しない。CHR012 は `rules.CHR012` と bind が揃った作品だけの opt-in である。
- 検査は挿絵・タグ YAML を読取専用とし、本文や挿絵を書き換えない。執筆完了ゲートにはしない。

## 作品単位の METRON / CHRONOS / AUDIT_LOG フラグ

- 正本は config.md の「## 基本情報」表。METRON と CHRONOS は連動させ（両方 ON か両方 OFF。食い違いは設定エラー）、行なしは METRON / CHRONOS が OFF、AUDIT_LOG が ON。未知値・重複・読込失敗は設定エラー。
- 新規作品は既定 ON で、OFF はユーザー明示のときだけ（返答なしは「未応答・既定 ON」）。行なしの既存作品は従来どおり OFF。OFF で下書き → ON で洗練は、明示 OFF した作品の経路として残す。
- フラグは自動ワークフローの起動判定にだけ使い、明示された CLI は拒否しない。ON の検査結果は本文保存の完了と分け、既にある本文の完了を取り消さない。ON は当該作品の writing_bridge 場面作業を承認済みと扱う（課金生成・イベント上書き・画像は対象外）。詳細は `workflow-specification.md`「作品単位の METRON / CHRONOS / AUDIT_LOG フラグの詳細」。

## 執筆接続（writing_bridge）

- ON で対象場面にハッシュ一致の active run があるときは writing_bridge が検査責任を持ち、同じ版へ `metron_cli.py analyze` / `chronos_cli.py check` を重ねない。
- 正本反映は `permissions.publish` がある run の `publish` だけ。手編集で `_novel_text` を置換しない。`FINAL.md` だけでは完了にしない。
- ON の新規場面は、ハッシュ一致の active run が無ければ `prepare` から始める。進めないターンは `_novel_text` を増やさず「未計測／要対応」で止める。
- セッション開始ゲート: ON の作品で本文を書く前に `novel_project_check <作品> --check-inspection-layers` を実行し、未計測章があれば新規章を起草せず後追い計測を先に済ませる。
- 清書は自動計測しない。ON の作品で清書した章は計測が古くなり、後追い計測で戻す。詳細は `workflow-specification.md`「執筆接続（writing_bridge）の詳細」。

## Plan Mode の完了

- **企画完了 = Gate A ∧ Gate B**。`novel_project_check` の OK（骨格）だけでは完了としない。
- 既存作品の企画開始・再開は、洗練または Gate B 再実施を明示されない限り Gate A までで止め、「Gate A 完了・Gate B 未完了」と報告する。これは企画完了ではない。
- Gate A は必須ファイル・scaffold・character lint・project check。Gate B は作品タイプに応じた知識読込・設計の厚さ・洗練・設定監査（B4.5）・`_meta.md` への実施記録。B4.5 は本文が無い作品では矛盾0件を Gate B 完了の条件とし、本文がある作品では資料を直さず指摘をユーザーへ返す。
- Gate B の創作技法契約は、索引で選んだ **葉ファイルの selected** だけを `_meta.md` に残す。索引は選定補助であり再読対象ではない。新しい how_to は、明示の Gate B 再実施があるまで既存作品の selected に入らない。標準カタログへ葉を足すときは索引（または該当 README / 冒頭注記）と発動条件を書き、既存 selected は触らない。作業用索引があるときはそれが選定入口であり、標準だけの新葉は作業用へ追随するまで選定対象外（標準索引は発見用に併読する）。`pack_id` は任意の短縮であり、既存契約へ自動では付けない。
- 評価の既定は契約外。`reader.md` 等の工程正本は selected に無くても読む。ユーザーが契約に照らすと明示したときだけ selected（パック展開後）を再読する。
- **`working_path` に書いたパスは必ず自己完結ファイル**である。調整メモは `working_path` に書かない。実効パスは契約に working があればそれ、無ければ standard。合成しない。
- **ジャンルは作品プロファイルと別の分類軸である。** ジャンル軸が `genre/` の葉に該当する作品では、その葉を必須候補として selected にする（見送るなら理由付きで not_applicable）。`genre/*` をグループごと not_applicable にできるのは、ジャンル軸が「なし」のときだけ。
- **`not_applicable` はカタログ全未選択ではない。** プロファイル・ジャンル上の必須候補の見送りと、経路・プロファイル・ジャンルから外れるグループだけを理由付きで書く。
- `required_missing` は `_meta.md` の status ではない。selected の実在チェックから導く検査結果である。
- 手順の正本はスキル **`novel-planning`**。横断の厚さ・命名は `workflow-specification.md` の関連仕様を参照する。

## goal モード

- goal（完了条件つきの自律実行）で依頼されても、承認ゲートと第0層は緩和しない。事前承認は goal 文に明記した項目だけ有効で、git・外部送信・課金・秘密情報は明示された範囲でだけ扱う。手順と完了報告は スキル `novel-goal-mode`、人間向けの説明は `docs/workflow/goal-mode.md`。

## ルールとドキュメント

- ルール・スキル更新は `.rulesync/` を主編集先とし、`rule-authoring.md` に従う。
- 人間向け操作説明は `docs/` に置き、`docs-writing.md` に従う。
- `tools/` は共有・正規運用の Python ツール、`tools_temp/` は短命な試行に使う。
- `_how_to/` の恒久的なルール化・雛形更新は、ユーザーの明示依頼と `_how_to.example/` 側の検討を要する。

## 詳細仕様の参照先

| 作業 | 正本 |
| --- | --- |
| Plan / Source Material / Writing / Refinement | 該当スキルと `workflow-specification.md` |
| Tag / Manga / Illustration / Cover / Publishing | 該当スキルと `workflow-specification.md` |
| Reader / Editor Score / Consistency Audit / Reader Walk | `novel-reader-output` / `novel-evaluation-output` / `novel-reader-walk` |
| METRON / CHRONOS / AUDIT_LOG | `workflow-specification.md` と `docs/architecture/` |
| 執筆接続 | `writing_bridge` と `docs/architecture/writing-bridge.md` |
| Rulesync | `docs/rulesync.md` と `rule-authoring.md` |
| goal モード（完了条件つきの自律実行） | `novel-goal-mode` |
