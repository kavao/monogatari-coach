# Planning

このガイドでは、新しい作品や既存作品の企画・設計を整え、執筆に入れる状態へ進める流れを説明します。

## このドキュメントを使う場面

次のような指示を出すときに使います。

- 新しい小説を企画から起こしたい
- 「一からストーリーを出して」「悪役令嬢ものの話を考えて」のように、物語案を一から出してほしい（案を出す前に、該当ジャンルの `genre/` 資料を読みます。案は型名ではなく話として出てきます）
- `proposal.md` など企画ファイルを一つ作りたい
- 既存作品の企画作業を始める、または企画の文脈で「続きを頼む」「企画をそろえて」など再開したい
- 既存の設計を読み直して、心理・章構成・人物プロフィールを厚くしたい
- 執筆前に必要なファイルが揃っているか確認したい

## 案は話として出てきます

Monogatari Coach は、物語案・`proposal.md` のログライン・あらすじ・キャラクター紹介・チャットモードのあらすじを、「誰が、どういう状況で、何を賭けて、どうなるか」が読める文章で出します。「断罪回避型 × 前世知識」のような型名や、ジャンル資料の名前・ID は書きません。型名を並べた案は設計図にすぎず、どこが気に入らないかを言いにくいためです。

気に入らない点は、話の言葉のまま伝えてください（例: 「この兄はいらない」「結末は二人とも生き残ってほしい」）。Monogatari Coach が、どの設計を変えればよいかを内部で対応づけます。

どの型やジャンル資料を使ったかを知りたいときは、次のように頼むと、案とは別の節で設計の内訳を出します。

```text
この案の設計を見せて
```

設計の内訳は、作品の `_meta.md` の Gate B 記録（「提示層での現れ」）にも残ります。書き方の基準は `_how_to.example/synopsis_presentation.md` です。

## チャットへの指示文

これだけで動きます。

```text
企画書と設計書を作ってください。
```

新規作品として始める場合は、次のように指示できます。

```text
新しい小説として起こしてください。
```

企画ファイルを一つ新しく作る依頼でも、Monogatari Coach は新規・既存の経路に応じて必須ファイルの不足を確認し、足りない兄弟と検査まで進めます。既存作品では「続きを頼む」「企画をそろえて」だけでも、企画作業の文脈なら不足確認から再開します。作品を指定して次のように頼めます。必須ファイルが揃った作品の一行修正や指定箇所だけの改稿は、この一式補完の対象になりません。

```text
novels/NNN_作品名/ の企画作業を再開してください。
```

既存作品の設計を厚くしたい場合は、作品フォルダも添えます。

```text
novels/NNN_作品名/ の設計を確認して、足りないところを洗練してください。
```

## Monogatari Coach が行うこと

Monogatari Coach は、企画を **Gate A（骨格）** と **Gate B（知識・厚さ）** の二段で進めます。ファイルが揃っただけでは企画完了になりません。

### Gate A（骨格）

必須ファイルとディレクトリを揃え、機械チェックを通します。

| ファイル | 内容 |
|----------|------|
| `proposal.md` | 作品名、ログライン、ターゲット層、あらすじ、魅力 |
| `design_specification.md` | テーマ、コンセプト、章構成、相関図 |
| `config.md` | novel_ID、writer_code、ジャンル、キーワード、METRON / CHRONOS / AUDIT_LOG の ON / OFF |
| `character.md` | 登場人物のプロフィール、課題、目的、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術 |
| `_meta.md` | 進捗、伏線、次回タスク、**Gate B 記録** |
| `_meta.yaml` | 画像生成の機械可読設定（NovelAI ポーション等） |

新規作品では、資料を揃えたあと次を実行します。

```bash
# 作品フォルダをまだ作っていない場合は、先にオンボーディングする
uv run python tools/novel_onboard.py novels/NNN_作品名

# 既に config.md がある場合の不足分補充
uv run python tools/novel_scaffold.py novels/NNN_作品名
```

続いて人物構造とプロジェクト準備を確認します。

```bash
uv run python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan
uv run python tools/novel_project_check.py novels/NNN_作品名

# METRON / CHRONOS が ON の作品で保存先も確認する
uv run python tools/novel_project_check.py novels/NNN_作品名 --check-inspection-layers
```

新規は採番から、既存作品の企画再開では再採番しません。合否はコマンドの終了コードを正とし、実行した各 `novel_project_check.py` の終了コードを報告します。

既存作品の企画を始める・再開する場合も、Monogatari Coach は不足ファイルだけを補い、その作品の Gate A を確認します。`config.md` が欠けていればフォルダ名の番号を `novel_ID` に使い、METRON / CHRONOS はユーザーの確認があるまで OFF のままにします。本文の続きにはこの不足確認を適用しません。

`--check-inspection-layers` を付けると、`config.md` の「## 基本情報」表にある METRON / CHRONOS / AUDIT_LOG と保存先を確認します。METRON / CHRONOS は行なしまたは `OFF` が対象外、ON なのに保存先が無い場合は WARN（終了コード 0）です。AUDIT_LOG は行なしが ON です。不正値・重複・読込失敗は設定エラー（終了コード 1）になります。

新規作品では、Monogatari Coach は METRON / CHRONOS を標準で ON にします。起こしのときに確認し、OFF にしたいときだけ指示します。行が無い既存作品は従来どおり OFF のままです。ON にした作品では `_metron/` と `chronos/` を用意してから上の確認コマンドを実行します。

オンボーディング時に確認への返答がない場合は、**「未応答・既定 OFF」** として `config.md` に記録します。従量 API の量を抑えるため、まず OFF で下書きし、書き終えた章から ON にして洗練する進め方が標準です。最初から ON にする場合だけ、`novel_onboard.py` に `--metron ON` / `--chronos ON` を指定してください。OFF で起こした作品は、いつ ON にするかを `_meta.md` の「検査レイヤの予定」に残します。API の量を抑えるため、OFF で下書きして書き終えた章から ON にして洗練する進め方は [Writing bridge の「OFF で下書きし、あとで ON にして洗練する」](../architecture/writing-bridge.md#off-で下書きしあとで-on-にして洗練する) を参照してください。`--metron` と `--chronos` は同じ値にしてください。違う値を指定すると、フォルダを作る前にエラーで止まります。`--dry-run` では予定フラグと保存先だけを表示し、ファイルは作成しません。

### Gate B（知識・厚さ）

作品の経路とプロファイルを判定し、必要な創作技法だけを読んで設計を厚くします。索引は選ぶための入口であり、あとから読み直す対象は `_meta.md` に残した **葉ファイル（selected）** です。新しい技法ファイルをカタログに足しても、指示のない既存作品の selected は増えません。

1. **分類**: 作品経路（新規起こし / 資料取り込み / 既存洗練）、作品プロファイル（一般 / mature / body_therapy 等・複数可）、ジャンル（`genre/` の葉。例: 悪役令嬢 → `genre/akuyaku_reijo.md`。なしも可）を決める
2. **必読選択**: 作業用 `_how_to/_index.md` があるときはそれを選定の入口にし、あわせて標準 `_how_to.example/_index.md` を発見用に開きます。標準にだけある葉は、作業用へ行を足すまで読みません。作業用が無ければ標準だけを開きます。該当する葉だけを読む（全件は読まない。索引そのものは selected に入れない）。ジャンルが該当する `genre/` の葉は必読です
3. **ユーザスキル**: 作業用 `_how_to/skills/_index.md` があるときはそれを選定の入口にし、標準 `_how_to.example/skills/_index.md` を発見用に開きます。作業用に無い雛形は追随するまで読みません。作業用が無ければ標準だけを開き、発動条件に当たるものだけ読む
4. **葉の読み方**: 契約の `working_path` に書いたパスは、必ず自己完結な1ファイルです。Monogatari Coach はそこだけを読み、標準本文と足し合わせません。調整メモは `working_path` に書きません。`working_path` が空なら標準を読みます
5. **抽選**: 必要なら選定レジストリで `pick`（使わない場合は理由を残す）
6. **タイトル命名**: 新規または改題時は候補5件以上。既存で記録がある場合は確認のみ
7. **設計の厚さ**: 初回は各章5項目以上 → 洗練後は原則2倍かつ最低10項目。Mermaid 相関図は必須
8. **洗練**: 自己評価 → プロット厚化 → 心理・シーン増 → プロフィール掘り下げ（省略しない）
9. **設定監査（B4.5）**: 洗練を終えた `character.md`・`world.md`・`design_specification.md` を読み直し、資料どうしの食い違いを矛盾／要確認／軽微に分けます。結果は `_reader/consistency_design_YYYYMMDD_HHMM.md` に保存され、`_meta.md` の評価履歴にも1行入ります。本文がまだない作品では、Monogatari Coach が矛盾と軽微を直して1回だけ見直し、矛盾が0件になるまで企画完了にしません。本文がすでにある作品では、本文との食い違いを生まないよう資料を直さず、指摘をそのまま報告します。要確認（作者の意図で決まるもの）はどちらの場合も直さずに報告します
10. **記録**: `_meta.md` の Gate B 記録へ、selected / not_applicable / 選定補助、任意の pack_id と差分、スキル、pick、厚さを残す。パックは既存作品へ自動では付きません。not_applicable はカタログの残り全部ではなく、プロファイル・ジャンル上の必須候補の見送りと、外れるグループ（ジャンルが「なし」のときの `genre/*` など）だけです。選んだ葉がファイルとして無いときは企画完了にしません（欠落は検査結果であり、`_meta.md` の status 欄には書きません）
11. **提示層での現れ**: 選んだジャンル資料の型ごとに、それがログライン・あらすじ・キャラクター紹介のどの一文（人物・出来事）として現れたかを、Gate B 記録に1行ずつ残す。型名はこの記録の中にだけ書き、それらの欄には書かない

既存作品の `_meta.md` に旧形式のパス一覧がある場合、Monogatari Coach は一括では書き換えません。新しい形式は新規の企画完了と、ユーザーが Gate B の再実施を指示した作品だけに使います。旧形式（`how_to/` で始まるパス、プレフィックス無し、索引と葉の混在）は、後続の実在チェックで警告します。確認だけするときは次を使います（`_meta.md` は書き換えません。Gate A の必須ではありません）。

```bash
uv run python tools/novel_howto_contract_check.py novels/NNN_作品名
```

`character.md` 作成時は、命名・トロープ・プロフィール候補の抽選前に **選定レジストリ** を確認します（`uv run python tools/novel_pick_registry.py validate`、スキル **content-pick-registry**）。詳細は [ユーザスキル](user-skills.md) を参照してください。

## エピソード・トロープの抽選（一般向け）

設計を厚くする際、一般向け（全年齢）のエピソードフックや進行パターンを抽選できます。

1. `uv run python tools/novel_pick_registry.py list --domain episode --visibility public` で ID を確認
2. `uv run python tools/novel_pick_registry.py pick <list_id>` で具体シチュエーションを抽選
3. 抽選結果を `design_specification.md` のストーリー節やシーン案へ取り込む

詳細は [`_how_to.example/skills/episode-general-pick/SKILL.md`](../../_how_to.example/skills/episode-general-pick/SKILL.md) を参照してください。

## ユーザーが確認できるもの

作品フォルダ `novels/<作品>/` に、企画・設計・人物・世界観のファイルが揃います。あわせて `_meta.md` の Gate B 記録で、読んだ葉（selected）と読まなかった理由（not_applicable）を確認できます。not_applicable はカタログの残り全部ではなく、プロファイル・ジャンル上の必須候補の見送りと、外れるグループ（ジャンルが「なし」のときの `genre/*` など）です。索引だけの行は選定のメモであり、あとから技法を読み直す一覧ではありません。標準カタログへ技法ファイルを足しても、指示のない作品の selected は増えません。作業用 `_how_to/_index.md` があるときは、標準にだけある新しい葉は作業用へ行を足すまで選定の対象になりません。任意の `pack_id` も、Gate B に書いた作品以外には付きません。足し方は [`docs/project-structure/how-to-area.md`](../project-structure/how-to-area.md) です。

Gate B の完了報告には、設定監査の件数と、要確認（作者が決める項目）の一覧が出ます。監査の中身は `_reader/consistency_design_YYYYMMDD_HHMM.md` で確認できます。企画のあとで設定だけを改稿したときは、報告の末尾に `設定資料の一貫性を監査して` という指示文が出ます。監査の詳しい見方は [Reader Output](reader-output.md#consistency-audit一貫性監査) です。

執筆前には次のコマンドで不足がないか確認できます。

```bash
uv run python tools/novel_project_check.py novels/NNN_作品名
```

`novel_project_check.py` は既定で `character.md` の構造 lint（`plan` profile）も実行します。詳細だけ先に見る場合は次を使います。

```bash
uv run python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan
```

不足項目の追記案や、表形式から `- **ラベル**:` 形式への変換案も見たい場合は、次のようにします。

```bash
uv run python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan --suggest
```

構造 lint を執筆前チェックから外す場合のみ `--no-character-structure` を付けます。

```bash
uv run python tools/novel_project_check.py novels/NNN_作品名 --no-character-structure
```

**新規企画と、明示された既存作品の洗練は、Gate A と Gate B の両方を満たすまで企画完了にはしません。既存作品の企画開始・再開は、洗練または Gate B 再実施の明示がなければ Gate A までで止め、「Gate A 完了・Gate B 未完了」と報告します。** Gate A だけの報告は企画完了ではありません。Gate A と Gate B がそろったら、本文執筆、Tag Mode、Manga Tag Mode へ進めます。Tag Mode で服・資料ポーズなど作品固有の `variant_id` が要る場合は、執筆前に `_meta.md` の**キャラタグ方針**（カスタム要素）へ列挙しておくとよいです（**テンプレート一式**の指示文は [instruction-driven.md §G](instruction-driven.md#g-キャラクター画像タグを作るtag-mode)）。

## 関連ページ

- 原資料から始める場合は [Source Material Intake](source-material-intake.md) を参照してください。
- 指示文の一覧は [指示出しベースのワークフロー](instruction-driven.md) を参照してください。
- 作品フォルダの構造は [Project Structure](../project-structure/index.md) を参照してください。
- 受け入れ条件は [開発者向け検証](../developer-verification.md) の Plan Mode Gate A / Gate B を参照してください。
