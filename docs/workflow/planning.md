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

Monogatari Coach は、執筆前に必要なファイルを確認し、不足しているものを作成・更新します。

| ファイル | 内容 |
|----------|------|
| `proposal.md` | 作品名、ログライン、ターゲット層、あらすじ、魅力 |
| `design_specification.md` | テーマ、コンセプト、章構成、相関図 |
| `config.md` | novel_ID、writer_code、ジャンル、キーワード |
| `character.md` | 登場人物のプロフィール、課題、目的、関係 |
| `world.md` | 世界観、地理、歴史、社会、技術 |
| `_meta.md` | 進捗、伏線、次回タスク |
| `_meta.yaml` | 画像生成の機械可読設定（NovelAI ポーション等） |

新規作品では、資料を揃えたあと次を実行します。

```bash
python tools/novel_scaffold.py novels/NNN_作品名
```

作成後は、必要に応じて設計の弱い部分を自己評価し、心理描写や具体的なシーンを増やします。

## ユーザーが確認できるもの

作品フォルダ `novels/<作品>/` に、企画・設計・人物・世界観のファイルが揃います。

執筆前には次のコマンドで不足がないか確認できます。

```bash
python tools/novel_project_check.py novels/NNN_作品名
```

人物プロフィールの構造を先に確認する場合は、次を実行します。

```bash
python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan
```

不足項目の追記案や、表形式から `- **ラベル**:` 形式への変換案も見たい場合は、次のようにします。

```bash
python tools/novel_character_md_check.py novels/NNN_作品名 --profile plan --suggest
```

執筆前チェックに character.md の構造 lint も含める場合は、次のようにします。

```bash
python tools/novel_project_check.py novels/NNN_作品名 --require-character-structure --character-profile plan
```

結果が OK になったら、本文執筆、Tag Mode、Manga Tag Mode へ進めます。

## 関連ページ

- 原資料から始める場合は [Source Material Intake](source-material-intake.md) を参照してください。
- 指示文の一覧は [指示出しベースのワークフロー](instruction-driven.md) を参照してください。
- 作品フォルダの構造は [Project Structure](../project-structure/index.md) を参照してください。
