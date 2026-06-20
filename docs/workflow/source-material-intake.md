# Source Material Intake

このガイドでは、既存のメモ、プロット、設定、下書きなどを Monogatari Coach の作品フォルダへ展開するときの流れを説明します。

## このドキュメントを使う場面

次のような資料がすでにあるときに使います。

- `source_material/` に原資料を置いている
- `novels/_import/` に取り込みたい資料群がある
- メモや下書きを `proposal.md` / `design_specification.md` / `character.md` などへ整理したい
- 既存作品の資料を崩さず、参照用に保全しながら制作へ進みたい

## チャットへの指示文

これだけで動きます。

```text
source_material の資料を元に作品を展開してください。
```

`novels/_import/` を使う場合は、次のように指示できます。

```text
novels/_import/ の資料を Monogatari Coach 形式へ展開してください。
```

## Monogatari Coach が行うこと

Monogatari Coach は、原資料を読み、作品フォルダ内の標準ファイルへ対応付けます。

| 原資料の内容 | 展開先 |
|--------------|--------|
| 作品名、ログライン、あらすじ | `proposal.md` |
| テーマ、章構成、相関図 | `design_specification.md` |
| 世界設定、用語、歴史 | `world.md` |
| 登場人物表、口調、背景 | `character.md` |
| 本文下書き、シーン案 | `_novel_text/novel_textXX.md` |

新規作品の場合は、`tools/novel_code_allocate.py` で次の作品番号を確認します。既存作品がある場合は、重複作成せず、更新対象を見極めます。

## ユーザーが確認できるもの

展開後、主に次のファイルやフォルダが作られます。

- `novels/<novel_code>_<作品名>/proposal.md`
- `novels/<novel_code>_<作品名>/design_specification.md`
- `novels/<novel_code>_<作品名>/config.md`
- `novels/<novel_code>_<作品名>/character.md`
- `novels/<novel_code>_<作品名>/world.md`
- `novels/<novel_code>_<作品名>/_meta.md`
- `novels/<novel_code>_<作品名>/_novel_text/`
- `novels/<novel_code>_<作品名>/_reader/`
- 必要に応じて `novels/<novel_code>_<作品名>/_source_material/`

原資料は改変せず、必要に応じて `_source_material/` へ参照用として退避します。

## 取り込み後の確認

展開後は、次の確認が行われます。

```bash
# novel_code と config.md の整合を確認する
python tools/novel_code_allocate.py verify novels/NNN_作品名

# 執筆前に必要なファイル・ディレクトリの揃いを確認する
python tools/novel_project_check.py novels/NNN_作品名
```

確認が通ったら、展開済みの `novels/<作品>/` を正として、計画、タグ作成、執筆へ進みます。

## 関連ページ

- 指示文の一覧は [指示出しベースのワークフロー](instruction-driven.md) を参照してください。
- 作品フォルダの構造は [Project Structure](../project-structure/index.md) を参照してください。
- 採番ツールは [Tools](../tools/index.md) を参照してください。
