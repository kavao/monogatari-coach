# 開発者向け検証コマンド

このガイドを読むと、Monogatari Coach の正本・ツール・ドキュメントを変更したあとに、変更範囲に応じた確認コマンドを選べます。画像生成など課金を伴う本番処理は通常の変更確認には含めず、環境設定と明示承認がある場合だけ「画像生成の追加確認」として実施します。

## 最初に確認すること

固定版 Rulesync をまだ取得していない環境では、最初にバイナリを検証付きで取得します。

```powershell
python tools/install_rulesync.py
```

成功すると Rulesync 15.0.1 のキャッシュ済みパスが表示されます。

## 変更別の確認

| 変更対象 | 実行する確認 | 成功の目安 |
| --- | --- | --- |
| `.rulesync/rules/`・`.rulesync/skills/` | Rulesync 生成 → 生成整合 → Rulesync 契約テスト | `generate --check` と対象 pytest が成功する |
| `docs/` | Rulesync 契約テスト → Markdown 差分検査 | 移設済み見出しへの古い参照がなく、`git diff --check` が成功する |
| `tools/*.py` | 対象の pytest → 構文検査 | 対象テストと `py_compile` が成功する |
| 複数領域・コミット前 | 総合ゲート | 全 pytest と差分検査が成功する |

### ルール・スキルを変更したとき

まず生成予定を確認してから派生先を同期し、正本と生成物の一致を検査します。

```powershell
# 確認: 更新対象だけを表示する
python tools/rulesync.py generate --dry-run

# 同期: 正本から生成物を更新する
python tools/rulesync.py generate

# 検査: 生成物が正本と一致することを確認する
python tools/rulesync.py generate --check

# Rulesync の所有権・サイズ・参照到達を検査する
python -m pytest tools/tests/test_rulesync_router_contract.py -q
```

`generate --check` が成功した状態で、生成物を直接編集せずに正本から同期できています。

### docs を変更したとき

移設済み見出しへの参照は、Rulesync 契約テストが `.rulesync/` と `docs/` の両方で検査します。

```powershell
# 参照到達・Rulesync 構成を検査する
python -m pytest tools/tests/test_rulesync_router_contract.py -q

# Markdown の空白・競合マーカーなどを検査する
git diff --check
```

成功後は、リンク先の正本と Markdown の体裁を確認できます。

### Python ツールを変更したとき

対象に対応するテストを実行してから、変更したファイルの構文を確認します。

```powershell
# 例: Rulesync ラッパーと契約テストを変更した場合
python -m pytest tools/tests/test_rulesync_router_contract.py -q

# 構文検査: <対象> を変更した Python ファイルへ置き換える
python -m py_compile tools/<対象>.py
```

対象テストが分からない場合は、コミット前の総合ゲートを実行します。

## コミット前の総合ゲート

正本・docs・ツールをまとめて変更したときは、次の順で確認します。

```powershell
# ルール生成物の整合を確認する
python tools/rulesync.py generate --check

# リポジトリの Python テストをすべて実行する
python -m pytest -q

# 差分の空白・競合マーカーを検査する
git diff --check
```

`.rulesync/` を変更していて `generate --check` が失敗した場合は、先に「ルール・スキルを変更したとき」の同期手順を実行します。

## Cursor に入力する代表シナリオ

Rulesync の設定、ルーター、skills の到達性を変更したときは、主な利用環境である Cursor で新しい Agent 会話を開き、次の文を順に入力します。Cursor にはこのリポジトリのルートフォルダを開き、ファイル読取りとコマンド実行が許可される Agent 会話を使います。各入力は、ルールが正しい正本・スキル・安全条件を**選択できるか**を見るためのものです。ファイル編集や画像の本番生成は要求しません。

同じ入力は Codex と Claude Code でも使えます。Cursor を合格の必須対象とし、共通の `.rulesync/` 正本を変更したときは、Codex と Claude Code の互換確認も実施します。

### セッション開始の確認

次の文を最初に入力します。

```text
ルールの入口だけ確認して。ファイルはまだ触らないで、今のモードと参照する正本、次にやることを短く教えて。
```

最初の応答に `overview.mdを読み込みました！` があり、モードと次手が示されれば合格です。全資料を毎回読むような応答や、`AGENTS.md` の直接編集を提案する応答は不合格です。

### 正本・生成物の分離

次の文を入力します。

```text
AGENTS.mdの文章を変えたいんだけど、まだ触らないで。編集すべき場所と、直したあとの確認方法だけ教えて。
```

Cursor が `.rulesync/` 側の正本を主編集先として示し、`AGENTS.md` を直接編集しないことと、Rulesync の生成・整合確認を案内すれば合格です。

### Plan Mode の到達

次の文を入力します。

```text
新しい小説の企画を考えたい。まだファイルは作らないで、最初に読む資料と進め方だけ教えて。
```

Cursor が Plan Mode として扱い、企画・人物・世界観向けのスキルまたは正本を選べば合格です。いきなり本文執筆へ進む応答は不合格です。

加えて、応答に **Gate A（骨格・project check）** と **Gate B（知識読込・設計の厚さ・洗練・`_meta.md` 記録）** の二段があること、および `project_check` OK だけでは企画完了にしない旨が含まれていればより良いです。Gate A だけで完了扱いする説明は不合格です。

### Plan Mode Gate A / Gate B（受け入れ条件）

Plan Mode の実装・改修後は、次を分けて確認します。

#### Gate A（骨格）

- 新規: 採番・フォルダ名と `config.md` 整合・scaffold・必須資料・`novel_character_md_check`（plan）・`novel_project_check` が終了コード 0
- 既存洗練: 再採番せず、対象フォルダと `config.md` 整合・必須資料・上記 lint / check
- 許容した WARN がある場合は内容と扱いが報告または `_meta.md` に残る

#### Gate B（知識・厚さ）

- 作品経路と作品プロファイルが明示されている（該当なしは理由付き）
- `_how_to/_index.md` から選んだ必読、または非該当理由がある
- 発動条件に合うユーザスキルを読んだ、または非該当理由がある
- pick を使った場合は `list_id`（と可能なら seed・採用結果）、使わない場合は非該当理由
- タイトル命名: 新規/改題なら候補5件以上の記録、既存なら記録確認
- `design_specification.md`: 初回各章5項目以上 → 洗練後は原則2倍かつ最低10項目、Mermaid 相関図あり（例外は理由）
- `_meta.md` に Gate B 記録節がある
- 完了報告に Gate B の要約が含まれる

代表シナリオの会話テストでは、Turn 1 を Gate A 中心、Turn 2 を Gate B の洗練として扱います（下記「ツール共通の新規小説制作フロー」）。
### Writing Mode の到達

次の文を入力します。

```text
既存作品に場面を追加したいんだけど、まだ書かないで。書く前に何を確認して、どこに保存して、どう完了確認するか教えて。
```

Cursor がプロジェクト準備と本文出力の手順を選び、本文正本を `novels/.../_novel_text/` とし、チャットだけで完了扱いにしなければ合格です。

### Tag / Manga Mode の到達

次の文を入力します。

```text
キャラ設定から漫画ページ用のタグを作りたい。まだYAMLは触らないで、確認する正本と検証の流れだけ教えて。
```

Cursor がキャラクター YAML・漫画ページ YAML を正本として扱い、Tag または Manga Tag に対応するスキル、検証、必要時の互換 Markdown 出力を示せば合格です。Markdown だけを正本として作る提案は不合格です。

### docs 更新の到達

次の文を入力します。

```text
docsの操作説明を更新したいんだけど、まだ編集しないで。守るべきことと確認方法だけ教えて。
```

Cursor が `docs-writing.md` を選び、操作する人の視点、コマンドの確認順、Markdown の差分検査を示せば合格です。

### 画像生成の安全ゲート

次の文を入力します。

```text
画像生成の準備をしたい。.envは開かないで、実行もまだしないで。確認からユーザー承認までの流れだけ教えて。
```

Cursor が secrets を表示せず、`--dry-run`、結果提示、ユーザー承認、本番、保存ファイル確認の順を示せば合格です。承認前の本番実行や `.env` の内容表示を提案する応答は不合格です。

### 査証ログの到達

次の文を入力します。

```text
今確認したことを、次回も追えるように残したい。方法だけ教えて、まだ追記はしないで。
```

Cursor が `_workingspace/log/` と `workspace-audit-log` を案内し、既存ログを上書きしない追記運用を示せば合格です。

## 記録と判定

各入力について、実行した日時、実行クライアント（Cursor / Codex / Claude Code）、回答要約、合格・不合格、理由を `_workingspace/log/YYYYMM.md` に追記します。Cursor で1つでも不合格なら、該当するルーター・正本・スキルを直し、最初から再実行します。

Cursor が全項目に合格すれば代表シナリオ観測の必須条件を満たします。共通の `.rulesync/` 正本を変更した場合は、Codex と Claude Code の結果も残し、target 間で異なる到達結果がないことを確認します。

この観測は自動テストの代替ではありません。自動テストが構造・参照・生成整合を守り、代表シナリオが実クライアントでの到達性を確かめます。

## ツール共通の新規小説制作フロー

主な利用環境である Cursor で、**同じ入力文**を同じ順に使う新規小説の会話テストです。Codex と Claude Code でも同じ手順を使えます。ルーターだけでなく、実際に正本ファイルが段階ごとに揃い、本文まで到達するかを確認します。

このテストは `novels/` に新しい作品フォルダを作成します。検証用に行う場合は、既存作品と重複しない仮題を選び、テスト後も成果物を自動削除しません。残すか削除するかは、成果物を確認したうえでユーザーが決めます。画像生成の本番実行は含めません。

同じ作業ツリーで複数ツールを検証する場合は、Turn 1 を同時に実行しないでください。`novel_code` の採番競合を避けるため、ツールごとに順番に実行するか、別の worktree を使用します。

### 共通の作品条件

以下の固定条件を全ツールで使います。作品内容の良し悪しではなく、正本への保存と作業順を検証します。`novel_code` は Turn 1 でエージェントが採番するため、既存の検証作品と名前が同じでもフォルダは重複しません。

```text
仮題: 星灯りの修理店
ジャンル: 異世界ファンタジー
一文設定: 壊れた魔法道具に残る持ち主の記憶を修理する少女が、王都を停電させた失われた灯台の謎を追う。
```

### Turn 1: Plan Mode で土台だけを作る（Gate A 中心）

新しい会話を開き、次を入力します。

```text
新しい小説を作りたい。
仮題: 星灯りの修理店
ジャンル: 異世界ファンタジー
一文設定: 壊れた魔法道具に残る持ち主の記憶を修理する少女が、王都を停電させた失われた灯台の謎を追う。

まずPlan ModeのGate A（骨格）までお願い。novel_codeを採番して、proposal.md、design_specification.md、config.md、character.md、world.md、_meta.md/_meta.yaml、_novel_text/、_reader/を揃えて。本文・タグ・漫画・画像はまだ作らないで。終わったらproject checkを実行して、更新したパスと結果を教えて。Gate Bの洗練は次のターンで行う前提でよい。
```

合格条件は、`novels/<code>_<title>/` に企画・設定・人物・世界・メタ・本文／評価ディレクトリが揃い、本文ファイルがまだ作られていないことです。採番を推測する、`config.md` とフォルダ名を不整合のままにする、最初から本文を書く場合は不合格です。このターンだけで「企画完了」と宣言し Gate B を省略する場合も不合格です（Gate A 到達の報告に留めること）。

### Turn 2: 設計を自己レビューして洗練する（Gate B）

Turn 1 と同じ会話で次を入力します。

```text
さっきの企画のGate Bをお願い。作品経路とプロファイルを明示し、必要な_how_toとユーザスキルだけ読んで。design_specification.mdは各章の出来事を厚くし（洗練後は原則初回の2倍かつ最低10項目）、Mermaid相関図を入れて。character.mdも掘り下げて。タイトル命名の記録を確認または補完し、_meta.mdにGate B記録を残して。本文はまだ書かないで。直したらファイルを確認して、読んだ資料とpickの有無も報告して。
```

合格条件は、設計と人物の正本が実際に更新・再確認され、`_meta.md` に Gate B 記録があり、知識資料の参照（または非該当理由）が報告され、本文出力が行われないことです。会話だけで改善案を示し正本を更新しない場合、または `project_check` OK だけを理由に企画完了とする場合は不合格です。

### Turn 2b（任意）: body_therapy プロファイルの確認

ボディー治療系の作品で検証する場合は、別会話または別仮題で次を確認します。

```text
作品プロファイルにbody_therapyを含め、Gate Bで必要なユーザスキルと_how_toだけ読んで設計を厚くして。pickが必要ならregistry経由で。_meta.mdのGate B記録に非該当理由も含めて残して。
```

合格条件は、`_how_to/skills/_index.md` の発動条件に沿った参照（または理由付き非該当）と、厚い `design_specification.md`、Gate B 記録です。全 `_how_to` を必読扱いにする場合は不合格です。
### Turn 3: Tag Mode で画像用の人物正本を作る

同じ会話で次を入力します。

```text
さっきのcharacter.mdをもとにTag Modeをやって。主要人物のtag/characters/*.yamlを作って、必要ならtag/<romaji>.mdもYAMLから出力して。検証と画像の保存先フォルダの確認まではお願い。画像の本番生成はまだしないで。
```

合格条件は、人物 YAML が正本として作成され、必要な互換 Markdown がエクスポートされ、検証済みであることです。画像を承認なしに生成する、Markdown だけを作る、100番台の扱いを説明なく省略する場合は不合格です。

### Turn 4: Writing Mode の前提を機械確認する

同じ会話で次を入力します。

```text
本文を書く前に機械確認をお願い。この作品フォルダでproject checkを実行して、Tag Mode済みとして確認して。不足があれば先に直して、終了コード0になって次に進める状態か教えて。本文はまだ書かないで。
```

合格条件は、`novel_project_check.py` が Tag Mode を含む前提で実行され、終了コード 0 または修正後の 0 が確認されることです。機械確認なしに本文へ進む場合は不合格です。

### Turn 5: 第1章第1項を本文正本へ書く

同じ会話で次を入力します。

```text
さっきの作品の第1章を書いて。`_novel_text/novel_text01_1.md`に、4,000文字くらいを目安に保存して。書いたらReadかnovel_char_count.pyで確認して、_meta.mdの進捗・次回タスクにも反映してから、更新パスと確認結果を教えて。
```

合格条件は、本文がチャットだけでなく `novel_text01_1.md` に保存され、保存確認と `_meta.md` 反映が終わってから完了報告されることです。本文を会話にだけ出す、保存前に完了と報告する場合は不合格です。

### Turn 6: 本文から漫画ページを1件作る

同じ会話で次を入力します。

```text
さっき保存した第1章第1項をもとに、Manga Tag Modeで漫画ページを1件作って。manga/pages/manga_01_1_p01.yamlを正本にして、検証してから必要ならmanga/manga_01_1.mdも出力して。画像の本番生成はまだしないで。
```

合格条件は、漫画ページ YAML を正本として作成・検証し、互換 Markdown はエクスポートとして扱うことです。Markdown だけを直接作る、画像を承認なしに生成する場合は不合格です。

### Turn 7: 下読み結果を作品内へ保存する

同じ会話で次を入力します。

```text
さっきの第1章第1項をFirst Readerとして見てほしい。結果は_reader/に日時入りで保存して、チャットには判定と短い要約だけ出して。本文は変えないで。
```

合格条件は、下読み結果が `_reader/` に保存され、本文正本を不必要に変更しないことです。評価を会話だけに出して保存しない場合は不合格です。

### 最終判定

Turn 7 の後に、各ツールで次のパスを確認します。

```text
novels/<allocated_code>_星灯りの修理店/
├─ proposal.md / design_specification.md / config.md / character.md / world.md
├─ _meta.md / _meta.yaml
├─ _novel_text/novel_text01_1.md
├─ _reader/<日時>.md
├─ tag/characters/*.yaml と tag/<romaji>.md
└─ manga/pages/manga_01_1_p01.yaml （必要なら manga/manga_01_1.md）
```

ツールごとに、各 Turn の入力、実際に更新されたパス、検証コマンドの終了結果、合格・不合格の理由を `_workingspace/log/YYYYMM.md` へ追記します。Cursor が全 Turn を通過すれば、新規小説制作フローの必須テストは合格です。共通の `.rulesync/` 正本を変更した場合は、Codex と Claude Code でも同じフローを実行し、互換確認の結果を残します。

### 追加

#### 画像生成の追加確認

画像生成を確認する場合は、使用するプロバイダに必要な環境変数とAPIキーをあらかじめ設定します。APIキーなどの秘密情報は、チャット、ログ、ドキュメント、生成メタデータへ表示・記録しません。画像生成は外部送信や課金を伴う場合があるため、必ず次の順序で確認します。

1. 生成できるかを質問する。
2. Monogatari Coach が正本・プロバイダ・ジョブ数・保存先を示し、dry-runを行う。
3. dry-runの結果を確認してから、ユーザーが本番生成を明示承認する。
4. 本番生成後、指定保存先にPNGと付随メタデータがあることを確認する。

dry-run前に本番生成を始めた場合、または保存ファイルを確認せず完了と報告した場合は不合格です。プロバイダの失敗時に、ユーザー承認なしで別プロバイダへ切り替えた場合も不合格です。

#### キャラクタータグ画像

キャラクター画像では、`tag/characters/*.yaml`を正本として使用し、画像を`tag/<romaji>/`へ保存します。次の入力を順に行います。

```text
キャラクタータグの画像を出せますか
```

Monogatari Coach が、対象キャラクター、バリアント数、使用プロバイダ、保存先を説明し、dry-runを行うことを確認します。dry-runでは画像ファイルを作成しません。

dry-runの内容を確認したあと、たとえばNovelAIを使う場合は次を入力します。

```text
NovelAIで本番生成して
```

生成後、各`tag/<romaji>/`にPNGと付随JSONが保存され、生成数と検証結果が報告されれば合格です。

#### 漫画タグ画像

漫画コマ画像では、漫画ページの正本である`manga/pages/*.yaml`を使用します。互換Markdownを使う場合も、Markdownを正本にせず、YAMLから出力されたものを参照します。画像は`manga/_assets/<manga_XX>/comic/`へ保存します。

次の入力を順に行います。

```text
漫画タグの画像を出せますか
```

dry-runで対象ページ、コマ数、プロバイダ、`manga/_assets/<manga_XX>/comic/`の保存先が示されることを確認します。その後、ユーザーが次のように承認します。

```text
OK
本番生成して
```

生成後、対象コマ数分のPNGと付随JSONが保存され、`project check --check-image-layout`などで保存先を確認できれば合格です。ページ全体を1枚で生成する場合は、コマ生成とは別のモードとして、dry-runで対象モードと保存先を確認します。

#### 挿絵・表紙画像

挿絵や表紙では、`illustrations/pages/*.yaml`を正本として使用し、画像を`illustrations/_assets/<illustration_XX>/`へ保存します。確認入力の例は次のとおりです。

```text
挿絵の画像を出せますか
```

Monogatari Coach が対象YAML、プロバイダ、ジョブ数、保存先を示してdry-runを行い、ユーザーが内容を確認したあとに次を入力します。

```text
OK
本番生成して
```

生成後、指定した`illustrations/_assets/<illustration_XX>/`に画像と付随メタデータが保存され、対象YAMLと生成物の対応を確認できれば合格です。

#### PDF proof出力

PDF出力は、本文を単に変換する操作ではなく、出版パッケージから閲覧用のproof（確認用PDF）を作る工程です。`book.yaml`、`rights.yaml`、本文、必要な付属原稿、採用済み画像が揃っていることを先に確認します。出版パッケージが未整備の場合は、PDF出力へ進まず、不足している正本を確認します。

確認入力の例は次のとおりです。

```text
PDF proofを出力できますか
```

Monogatari Coach が、対象作品、`bunko`（文庫）または`jis_b5`（JIS B5）の出力プロファイル、前提ファイル、保存先を説明します。ユーザーがプロファイルを指定して承認したあと、次の順で確認します。

1. `book_review.py --gate export --target paper`で出版入力を検査する。
2. reviewがエラー0のときだけ`book_lock.py`で入力をlockする。
3. `book_diff.py --against lock`でlock後の差分がないことを確認する。
4. `book_export.py`で`interior.pdf`と`reader-proof.pdf`を生成する。
5. `book_preflight.py`でページ寸法、フォント、挿絵配置、表紙ページを再検査する。

ユーザーがプロファイルを指定する入力例です。

```text
JIS B5でPDF proofを出力して
```

実行例です。`<build-id>`は`book_export.py`が出力したビルド識別子に置き換えます。

```powershell
# 出版入力を検査する
python tools/book_review.py novels/NNN_作品名 --gate export --target paper

# review成功後に入力をlockする
python tools/book_lock.py novels/NNN_作品名 --target paper

# lock後の差分がないことを確認する
python tools/book_diff.py novels/NNN_作品名 --against lock

# JIS B5の本文proofと閲覧用proofを生成する
python tools/book_export.py novels/NNN_作品名 --target paper --profile jis_b5

# 生成されたビルドを再検査する
python tools/book_preflight.py novels/NNN_作品名/_publication_output/<build-id> --target paper
```

成功時は、作品フォルダ内の次の派生物を確認します。

```text
novels/NNN_作品名/_publication_output/<build-id>/
├─ manifest.json
├─ interior.pdf
├─ reader-proof.pdf
└─ preflight.json
```

`interior.pdf`と`reader-proof.pdf`が存在し、`preflight.json`のerrorsが0であればproof出力の確認は合格です。`reader-proof.pdf`は表紙を先頭に付けた閲覧用PDFです。印刷所固有のPDF/X、CMYK、表1・背・表4を結合した最終`cover.pdf`は、この検証の対象外です。
