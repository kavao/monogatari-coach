---
name: novel-planning
description: >-
  「一からストーリーを出して」「〇〇ものの話を考えて」など新しい物語案を出すとき、
  および新規作品または既存作品の企画・設計フェーズで、proposal.md、
  design_specification.md、config.md、character.md、world.md、_meta.md などを揃え、
  執筆前確認へつなげる。資料不足時の作成順と確認観点を固定する。
  ジャンル軸を判定し、該当する genre/ の葉を案出しの前に読む。
  新規企画は Gate A / Gate B を完了する。既存作品の企画再開は Gate A で止め、
  洗練または Gate B 再実施の明示時だけ Gate B まで進める。
targets: ["*"]
---

## 目的

Plan Mode で、執筆前に必要な Monogatari Coach ファイルを揃え、「迷わず書ける状態」にする。

このスキルは、企画・設計・人物・世界観・メタ情報を整える作業手順を定める。執筆前の機械確認は **`novel-project-readiness`** を併用する。

**完了の定義**: 新規企画と、ユーザーが既存作品の洗練または Gate B 再実施を明示した場合は、Gate A と Gate B を完了してから企画完了と報告する。既存作品の企画開始・再開は、洗練または Gate B 再実施が明示されなければ不足ファイルを補って Gate A で止め、「Gate A 完了・Gate B 未完了」と報告する。これは企画完了ではない。短い正本は `.rulesync/rules/concepts.md`「Plan Mode の完了」。

## 使う場面

- ユーザーが「企画書と設計書を作って」「新しい小説として起こして」などと指示した。
- `proposal.md` / `design_specification.md` / `config.md` / `character.md` / `world.md` / `_meta.md` のいずれかを新しく作成するよう頼まれた。既存の未完了作品で欠けた必須ファイルを作る依頼も含む。
- 対象作品の企画作業を開始・再開するよう頼まれた。企画作業の文脈なら「続きを頼む」「企画をそろえて」も含み、明示的に不足確認を求められなくても既存ファイルの不足確認から始める。
- ユーザーが「一からストーリーを出して」「悪役令嬢ものの話を考えて」など、ファイル指定なしで新しい物語案を求めた。チャットで案だけを返す場合も、案を出す前に B1 の 1〜2 と 4（分類・ジャンル葉の選定と読込）を行う。
- Source Material Intake 後、展開済み資料を洗練したい。
- 既存作品について設計の洗練または Gate B 再実施を明示された。

企画作業を再開する場合は対象作品を特定する。「続きを頼む」「企画をそろえて」だけでも、文脈が企画作業なら6つの必須企画ファイルを確認する。チャットで案だけを出す依頼では作品フォルダを作らず、リポジトリ全体の一括巡回もしない。本文の続き・清書・追記はこの入口に含めない。必須ファイルが揃っている作品の一行修正や指定箇所だけの改稿はこの入口の対象外とし、依頼範囲を超えて一式を作り直さない。

## 作成・確認するもの

| ファイル | 役割 |
|----------|------|
| `proposal.md` | 作品名、ログライン、ターゲット層、あらすじ、キャラクター紹介、魅力 |
| `design_specification.md` | テーマ、コンセプト、章構成（厚さは Gate B）、ストーリー相関図、執筆スケジュール |
| `config.md` | novel_ID、writer_code、作品名、作者名、ジャンル、キーワード、METRON / CHRONOS / AUDIT_LOG の ON / OFF |
| `character.md` | 登場人物のプロフィール、課題、目的、口調、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術、組織 |
| `_meta.md` | 進捗、伏線、次回タスク、**Gate B 記録**、外部投稿用情報 |
| `_meta.yaml` | 画像生成の機械可読設定（現行: NovelAI ポーション）。雛形は `_how_to.example/_meta.yaml.example` |
| `_novel_text/`, `_reader/` | 本文と評価の保存先ディレクトリ |

## 分類（作業開始時に明記する）

Gate B を行うときは分類軸を分けて判定し、チャットまたは `_meta.md` の Gate B 記録に残す。該当資料がない場合も **「非該当」と理由**を書く。既存作品の Gate A のみを行う場合は企画経路だけを判定し、作品プロファイル・ジャンルの選定や Gate B 記録の内容作成は行わない。

| 軸 | 値の例 | 意味 |
|----|--------|------|
| **作品経路** | 新規起こし / 資料取り込み / 既存作品の洗練 | 作業の入り口。`資料取り込み` は内容タイプではなく **`source-material-intake`** へ分岐する経路 |
| **作品プロファイル** | 一般 / `mature` / `body_therapy`（**複数可**） | `_how_to`・ユーザスキル・必須構成要素の発動判定 |
| **ジャンル** | `genre/` の葉の relative_id（例: `genre/akuyaku_reijo.md`。**複数可**）/ なし | `genre/` の葉の発動判定。依頼文・`config.md` のジャンル・キーワードから判定し、索引の各行の説明と照合する。判断に迷うときはユーザーへ確認する |

## Gate A（骨格ゲート）

合否は **コマンド終了コードを正**とする。実行したすべての `novel_project_check.py`（`--check-inspection-layers` を含む）の終了コードを報告する。許容した WARN がある場合は内容と扱いを Gate B 記録（または完了報告）に残す。

### 新規起こし

作品フォルダがまだ無い、または新しい作品の採番前であれば新規起こしとして扱う。企画ファイルを1つだけ作る依頼も対象に含め、資料取り込みの有無と採番を先に確認し、手順 3〜8 で不足の兄弟・scaffold・検査を揃える。

1. 既存ファイルと `source_material/` / `_source_material/` の有無を確認する。資料取り込み経路なら本スキルの前に **`source-material-intake`** を優先する。
2. `novel-code-allocate` で採番し、フォルダ名と `config.md` の `novel_ID` を揃える。
3. 必須資料（proposal / design / config / character / world / `_meta.md`）を作成・更新する（中身の厚さは Gate B）。
4. `python tools/novel_scaffold.py novels/<作品>` で `_meta.yaml` と `references/novelai/` 等を揃える。
5. `python tools/novel_character_md_check.py novels/<作品> --profile plan`
6. `python tools/novel_project_check.py novels/<作品>`（不足時は `--bootstrap` 可。character 構造は既定で有効）
7. `config.md` 初回作成時は METRON / CHRONOS を両方 `ON` とするのが標準。2つは連動させ、作成時に1回だけ確認して両方に同じ値を書く。ユーザーが OFF を明示したときだけ両方 `OFF` にする（片方だけ ON は設定エラー）。同一ターンで応答が無いときは標準の ON で進め、`config.md` に **「未応答・既定 ON」** と記録する。`AUDIT_LOG` 行は省略してよい（行なしは ON）。清書中だけ止めたいときなど、必要な作品にだけ後から両方 `OFF` を書く。
8. METRON / CHRONOS を `ON` にした作品では、`chronos/` が無ければ `python tools/chronos_cli.py init novels/<作品>`、`_metron/` が無ければ作成する。そのあと `python tools/novel_project_check.py novels/<作品> --check-inspection-layers` を追加実行する。保存先不足の WARN は終了コード 0、設定エラーは終了コード 1 とする。

### 既存作品の企画作業

採番済みの作品フォルダがある場合は既存作品として扱う。企画作業を開始・再開したら必須企画ファイルの不足を確認し、欠落があればその作品だけを補完する。

1. **再採番しない。** `config.md` があれば対象フォルダとの整合を `novel_code_allocate.py verify` 等で確認する。`config.md` が欠けている場合は、フォルダ名の番号を `novel_ID` として補ってから整合を確認する。
2. Gate A の骨格補完では欠落した必須資料だけを作成する。既存ファイルの内容を厚くする作業は、ユーザーが洗練を明示した場合に Gate B で行う。
3. character lint と `novel_project_check` を実行する（上記と同じコマンド）。
   既存作品のフラグ行がない場合はパーサ上 `OFF`。新規起こしの既定は表へ ON を書く。既存を ON にするのはユーザー確認後。
   既存作品の欠落した `config.md` を補う場合も、新規起こしの既定 ON は適用しない。METRON / CHRONOS 行を省略して OFF のままとし、ユーザー確認後に限り両方 ON にする。フラグが ON の場合だけ `chronos/` / `_metron/` を用意して `--check-inspection-layers` を追加実行する。
4. 実行した各 `novel_project_check.py` の終了コードを報告する。

### 既存作品での停止位置

- 既存作品の企画作業の開始・再開は、洗練または Gate B 再実施を明示されない限り Gate A までで止める。「続きを頼む」「企画をそろえて」も同じ扱いとし、必須ファイルの補完と検査を行って「Gate A 完了・Gate B 未完了」と報告する。企画完了とは報告しない。
- `_meta.md` に既存の Gate B 記録があれば保持し、骨格補完では上書き・変換しない。記録が無い場合は Gate B 記録の見出しだけを用意し、B1 の知識選択・プロファイルやジャンルの記録・設計の洗練は行わない。
- ユーザーが設計の洗練または Gate B の再実施を明示した場合は、Gate B を完了報告前に満たす。
- 必須ファイルがすべて揃っており、指定箇所の修正だけを頼まれた場合は、その範囲で作業する。明示されていない Gate B の再実施や一式の作り直しは行わない。

## Gate B（知識ゲート）

新規企画と、ユーザーが既存作品の洗練または Gate B 再実施を明示した場合は、Gate A の前後どちらでもよいが **完了報告の前にすべて満たす**。既存作品の企画開始・再開では、そのどちらも明示されていなければ Gate A で止め、未完了として報告する。手順の詳細正本はこの節。横断の短い完了定義は `concepts.md`。タイトル命名の横断仕様は `workflow-specification.md` の関連仕様を参照する。

### B1. 知識の選択と読込

索引は選定にだけ使う。契約に残すのは、ここで選んだ **葉ファイル**である（`_index.md`、`episode_.md`、`epsode_common.md`、`epsode_mature.md` などの目次は selected にしない）。索引に新しい葉が載っても、既存作品の selected には足さない。追加はユーザーが Gate B 再実施を指示したときだけ。

1. **作品経路・作品プロファイル・ジャンル**を判定し記録する。
2. **索引入口**: `_how_to/_index.md` があればそれを選定入口として開き、`_how_to.example/_index.md` を発見用に併読する。作業用索引（および作業用の該当 README）に入口が無い標準の新葉は **選定対象外**。作業用索引が無ければ標準 `_how_to.example/_index.md` だけを開く。プロファイルとジャンルに応じた必読の葉だけを選ぶ（**全件必読にしない**）。ジャンル軸で判定した `genre/` の葉は必須候補であり、原則 selected にする（見送るなら 6(a) に理由を書く）。作業用索引に該当ジャンルの行が無く標準索引にだけある場合は、選定補助へ列挙し、ユーザーへ作業用索引への追随を案内する。
3. **ユーザスキル索引**: `_how_to/skills/_index.md` があればそれを選定入口とし、`_how_to.example/skills/_index.md` を発見用に併読する。作業用に無い雛形スキルは追随まで選定対象外。作業用が無ければ標準だけを開く。発動条件に当てはまるユーザスキルだけを読む（例: `body_therapy` → `character-body-pick`、mature 系フック → `episode-mature-pick`）。
4. **葉の読込**: 各葉は `relative_id`（先頭の `_how_to/` と `_how_to.example/` を除いた相対パス）で識別する。**`working_path` に書くパスは必ず自己完結ファイル**とする。そこに書いたらその1ファイルだけを読む。調整メモは `working_path` に書かず、`standard_path` を読む。標準と作業の合成はしない。
5. 命名・トロープ・プロフィール候補が必要なら **content-pick-registry** と `python tools/novel_pick_registry.py validate` のあと `pick <list_id>` する（path 直書きは fallback）。
6. **not_applicable** はカタログの未選択ファイルを全部書かない。書くのは次だけ。(a) プロファイル・ジャンル上の必須候補で selected にしなかった葉（`relative_id` と why）(b) 経路・プロファイル・ジャンルから外れるグループと why（例: ジャンル軸が「なし」のときの `genre/*`。ジャンル軸が該当する作品では `genre/*` をグループごと not_applicable にしない）。索引にあるだけの任意葉は書かない。selected にした葉の実効パスが実在しないときは Gate B 未完了とする（`required_missing` は `_meta.md` へ status として書かない。実在チェックの検査結果である）。

### B2. タイトル命名ゲート

- **新規起こし、またはタイトル変更時**: ユーザーが候補数を指定した場合はその件数、指定がない場合は最低 5 件を生成し、比較して 1 件採用する。採用は `proposal.md` / `config.md` の作品名へ反映。不採用候補がある場合は候補と却下理由を `config.md` の「資料上の別名」へ残す。参照: `_how_to.example/naming.md`、`workflow-specification.md`「タイトル命名ゲート」。
- **既存作品で命名記録がすでにある場合**: 再抽選せず、記録の存在を確認して Gate B 記録に「既存記録を確認」と書く。

### B3. 設計の厚さ

`design_specification.md` について:

1. **初回設計**: 各章に「誰が・何をした・何が変化した」が分かる具体出来事を **5 項目以上**置く。
2. **洗練後**: 各章を原則 **初回項目数の 2 倍**かつ **最低 10 項目**まで増やす。必要に応じて心理の変化も記す。
3. **ストーリー相関図（Mermaid）は必須**。例外は理由を Gate B 記録に残す。
4. **「執筆における必須構成要素」**は、作品プロファイルが `mature` / `body_therapy` 等で該当する場合に必須。非該当なら理由を記録する。

### B4. 洗練パス（必須）

「必要なら」で省略しない。旧 overview の第二パスを固定する。

1. 一度自己評価する（設定・心理・プロットの薄い箇所）。
2. プロット項目を厚くする（B3 の洗練後基準）。
3. 心理描写・具体シーンを増やす。
4. `character.md` のプロフィールを掘り下げる（**novel-character-profile**、必要ならユーザスキル・pick）。

### B5. Gate B 実施記録（`_meta.md`）

新規の Gate B 完了と、ユーザーが明示した Gate B 再実施では、`_meta.md` に **Gate B 記録**節を設け（雛形: `_how_to.example/meta.md`）、少なくとも次を残す。既存作品の旧形式リストは一括変換しない。既存の骨格補完で記録節がない場合は見出しだけを置き、既存記録があればそのまま保持する。骨格補完では Gate B の記録内容を新形式へ変換しない。

- 作品経路 / 作品プロファイル / ジャンル（なしの場合はその旨）
- **創作技法契約**（葉の契約。索引を selected に混ぜない）:
  - **pack_id**（任意）: `_how_to.example/howto_packs/<id>.yaml`。作業用 `_how_to/howto_packs/<id>.yaml` があればそれを自己完結として使う。既存作品へ自動では付けない。葉列挙（案 A）のままでよい
  - **pack_add** / **pack_exclude**: パックとの差分
  - **selected**: 各葉の `relative_id`、role、why、`standard_path` / `working_path` / `effective_path`、`bound_at`。status は `selected` のみ。パック展開分と重複して書いてよい
  - **not_applicable**: プロファイル・ジャンル上の必須候補の見送り、または経路・プロファイル・ジャンルから外れるグループ（例: ジャンル軸が「なし」のときの `genre/*`）。カタログ全未選択は書かない。pattern または `relative_id` と why
  - **選定補助**（任意）: 開いた索引パス。作業用索引があるときは、標準だけにあって作業用に無い葉の `relative_id` を列挙してよい。後工程の再読義務は無い。selected にしない
- 発動したユーザスキル（なければ非該当理由）
- pick の有無（使った場合: `list_id`・seed・採用結果。使わない場合: 非該当理由）
- タイトル命名: 実施 / 既存記録確認 / 例外理由
- 洗練前後の確認（初回章項目数目安 → 洗練後、相関図の有無）
- Gate A で許容した WARN（あれば）
- 検査レイヤ: 標準 ON で確認済み / ユーザー明示の OFF / 確認未応答で標準 ON

旧形式（`how_to/` プレフィックス、リポジトリ根からの相対だけ、索引を読んだ一覧に含む）は、第3段の実在チェックで WARN にする。第1段では正規化規則を守って新形式を書き、既存行は触らない。

完了報告には、selected の `relative_id` 要約をチャットへ含める。

## 執筆・清書での契約再読

スキル **`novel-text-file-output`** / **`novel-refinement-output`** が適用する。評価の既定は契約外（各評価スキル）。

1. 本文起草・清書の **前**（writing_bridge では **`prepare` の前**）に `_meta.md` の創作技法契約を読む。新形式なら **selected** と **pack 展開後の葉**だけを再読する（索引・`not_applicable` は再読しない）。`pack_id` があるときは、先に `python tools/novel_howto_contract_check.py novels/<作品> --strict` を実行する。終了コード 0 以外（欠落または `errors`）は再読を始めず **未完了**。0 のときだけ `--json` の `present` を再読集合とする。旧形式のパス一覧なら、索引・目次以外の葉だけを再読する（未変換の grandfather）。Gate B 節が無いときはカタログへ広がらず、「契約なし」と完了報告に書く。
2. 各 selected（または旧形式の葉）の実効パスを解決して Read する。`working_path` が契約にあればそれを自己完結として読む。無ければ `standard_path`。
3. 完了報告に、使った葉ごとに拠り所を1句書く。査証ログへ要約する（`AUDIT_LOG | OFF` ならログ省略）。
4. selected（旧形式では一覧の葉）に無い how_to を創作判断に使う場合は、先に契約を更新するか、使わずに進む。黙ってカタログへ広げない。`rewrite.md` など清書手順ファイルは本スキル群の工程正本であり、selected に無くても読んでよい。

## Feedback の扱い

既存作品に `judge_result.md` や `impression.md` がある場合は、該当する作家の `writer_profile.md` へ文体・作風の学びとして反映できるかを確認する。

ただし、作品固有の評価本文そのものは作家プロフィールへ丸写しせず、再利用できる傾向・注意点だけを抽出する。

## 関連

- 資料取り込み: `.rulesync/skills/source-material-intake/SKILL.md`
- 採番: `.rulesync/skills/novel-code-allocate/SKILL.md`
- 執筆前確認: `.rulesync/skills/novel-project-readiness/SKILL.md`
- 人物プロフィール: `.rulesync/skills/novel-character-profile/SKILL.md`
- 選定レジストリ: `.rulesync/skills/content-pick-registry/SKILL.md`
- 本文保存: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 清書: `.rulesync/skills/novel-refinement-output/SKILL.md`
- 操作説明: `docs/workflow/planning.md`
- 受け入れ条件: `docs/developer-verification.md`（Plan Mode Gate A / Gate B）
- 契約実在チェック（任意・非 Gate A）: `tools/novel_howto_contract_check.py`
- 任意参照（完了条件ではない）: 説得力の配分は `_how_to.example/episode/general/episode_reality.md`、失敗の許容は `episode_hindrance.md`（作業用があれば `_how_to/episode/general/`）
