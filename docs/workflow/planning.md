# Planning

このガイドでは、新しい作品や既存作品の企画・設計を整え、執筆に入れる状態へ進める流れを説明します。

## このドキュメントを使う場面

次のような指示を出すときに使います。

- 新しい小説を企画から起こしたい
- `proposal.md` や `design_specification.md` を作りたい
- 既存の設計を読み直して、心理・章構成・人物プロフィールを厚くしたい
- 執筆前に必要なファイルが揃っているか確認したい

## チャットへの指示文

これだけで動きます。

```text
企画書と設計書を作ってください。
```

新規作品として始める場合は、次のように指示できます。

```text
新しい小説として起こしてください。
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
| `config.md` | novel_ID、writer_code、ジャンル、キーワード、METRON / CHRONOS の ON / OFF |
| `character.md` | 登場人物のプロフィール、課題、目的、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術 |
| `_meta.md` | 進捗、伏線、次回タスク、**Gate B 記録** |
| `_meta.yaml` | 画像生成の機械可読設定（NovelAI ポーション等） |

新規作品では、資料を揃えたあと次を実行します。

```bash
python tools/novel_scaffold.py novels/NNN_作品名
```

続いて人物構造とプロジェクト準備を確認します。

```bash
python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan
python tools/novel_project_check.py novels/NNN_作品名

# METRON / CHRONOS が ON の作品で保存先も確認する
python tools/novel_project_check.py novels/NNN_作品名 --check-inspection-layers
```

新規は採番から、既存作品の洗練では再採番しません。合否はコマンドの終了コードを正とします。

`--check-inspection-layers` を付けると、`config.md` の「## 基本情報」表にある METRON / CHRONOS と保存先を確認します。行なしまたは `OFF` は対象外、ON なのに保存先が無い場合は WARN（終了コード 0）です。不正値・重複・読込失敗は設定エラー（終了コード 1）になります。

### Gate B（知識・厚さ）

作品の経路とプロファイルを判定し、必要な創作技法だけを読んで設計を厚くします。

1. **分類**: 作品経路（新規起こし / 資料取り込み / 既存洗練）と作品プロファイル（一般 / mature / body_therapy 等・複数可）を決める
2. **必読選択**: `_how_to/_index.md` から該当資料だけを読む（全件は読まない）
3. **ユーザスキル**: `_how_to/skills/_index.md` の発動条件に当たるものだけ読む
4. **抽選**: 必要なら選定レジストリで `pick`（使わない場合は理由を残す）
5. **タイトル命名**: 新規または改題時は候補5件以上。既存で記録がある場合は確認のみ
6. **設計の厚さ**: 初回は各章5項目以上 → 洗練後は原則2倍かつ最低10項目。Mermaid 相関図は必須
7. **洗練**: 自己評価 → プロット厚化 → 心理・シーン増 → プロフィール掘り下げ（省略しない）
8. **記録**: `_meta.md` の Gate B 記録へ、読んだ資料・スキル・pick・厚さを残す

`character.md` 作成時は、命名・トロープ・プロフィール候補の抽選前に **選定レジストリ** を確認します（`python tools/novel_pick_registry.py validate`、スキル **content-pick-registry**）。詳細は [ユーザスキル](user-skills.md) を参照してください。

## エピソード・トロープの抽選（一般向け）

設計を厚くする際、一般向け（全年齢）のエピソードフックや進行パターンを抽選できます。

1. `python tools/novel_pick_registry.py list --domain episode --visibility public` で ID を確認
2. `python tools/novel_pick_registry.py pick <list_id>` で具体シチュエーションを抽選
3. 抽選結果を `design_specification.md` のストーリー節やシーン案へ取り込む

詳細は [`_how_to.example/skills/episode-general-pick/SKILL.md`](../../_how_to.example/skills/episode-general-pick/SKILL.md) を参照してください。

## ユーザーが確認できるもの

作品フォルダ `novels/<作品>/` に、企画・設計・人物・世界観のファイルが揃います。あわせて `_meta.md` に Gate B 記録があることを確認できます。

執筆前には次のコマンドで不足がないか確認できます。

```bash
python tools/novel_project_check.py novels/NNN_作品名
```

`novel_project_check.py` は既定で `character.md` の構造 lint（`plan` profile）も実行します。詳細だけ先に見る場合は次を使います。

```bash
python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan
```

不足項目の追記案や、表形式から `- **ラベル**:` 形式への変換案も見たい場合は、次のようにします。

```bash
python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan --suggest
```

構造 lint を執筆前チェックから外す場合のみ `--no-character-structure` を付けます。

```bash
python tools/novel_project_check.py novels/NNN_作品名 --no-character-structure
```

**Gate A が OK でも、Gate B（知識読込・厚い設計・洗練・`_meta.md` 記録）が終わるまで企画完了にはしません。** 両方そろったら、本文執筆、Tag Mode、Manga Tag Mode へ進めます。Tag Mode で服・資料ポーズなど作品固有の `variant_id` が要る場合は、執筆前に `_meta.md` の**キャラタグ方針**（カスタム要素）へ列挙しておくとよいです（**テンプレート一式**の指示文は [instruction-driven.md §G](instruction-driven.md#g-キャラクター画像タグを作るtag-mode)）。

## 関連ページ

- 原資料から始める場合は [Source Material Intake](source-material-intake.md) を参照してください。
- 指示文の一覧は [指示出しベースのワークフロー](instruction-driven.md) を参照してください。
- 作品フォルダの構造は [Project Structure](../project-structure/index.md) を参照してください。
- 受け入れ条件は [開発者向け検証](../developer-verification.md) の Plan Mode Gate A / Gate B を参照してください。
