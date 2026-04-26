# Manga Prompt IR Migration Plan

## 方針

いきなり既存 Markdown 運用を捨てず、**構造化 IR を正本に昇格し、Markdown は互換出力として残す**。

ただし、IRそのものは執筆・変換途中で壊れたら作り直せる中間データとして扱う。守るべき中核は、YAMLの形そのものではなく、**日本語で入っている意味、人物の固定特徴、誰が誰に何をしているか、セリフや効果音の帰属**である。

## Phase 1: ルール正本の追加

- `.rulesync/skills/manga-prompt-ir/` を追加する。
- `schemas/character.py` と `schemas/manga_page.py` を Pydantic v2 モデルの正本にする。
- `examples/*.yaml` を、人間編集用 YAML の最小サンプルにする。
- 既存タグ系スキルから `manga-prompt-ir` を参照する。

完了状態:

- 新規タグ設計時に、YAML/JSON/Pydantic を優先する根拠が `.rulesync/` にある。
- Markdown 互換運用も破棄されていない。

## Phase 2: 作品フォルダへの導入

作品ごとに次の配置を採用する。

```text
novels/<作品>/
  tag/
    characters/
      <character_id>.yaml
    <romaji>.md
  manga/
    pages/
      manga_01.yaml
    manga_01.md
```

運用:

- `tag/characters/*.yaml` をキャラクター定義の正本にする。
- `manga/pages/*.yaml` を漫画ページ定義の正本にする。
- 既存バッチが必要な間は、YAML から `tag/<romaji>.md` と `manga/manga_XX.md` を生成または手動同期する。
- 小説本文からIRへ変換した直後は、構文よりも意味の欠落を優先して点検する。破綻が大きい場合は部分修正ではなくIR再生成でよい。

## Phase 3: 変換ツールの正式化

`tools_temp/` で試作してから、意図を整理して `tools/` へ正式反映する。

候補:

- `tools/novel_prompt_ir_validate.py`
  - YAML を Pydantic で検証する。
  - 参照されている `character_id` が存在するか確認する。
- `tools/novel_prompt_ir_render.py`
  - YAML から自然文プロンプト、タグ列、negative tags、テキスト要素を出力する。
- `tools/novel_prompt_ir_export_md.py`
  - YAML から既存互換の `tag/<romaji>.md` / `manga/manga_XX.md` ブロックを出力する。

## Phase 4: 既存バッチの入力拡張

`tools/forge_novel_tag_batch.py` と `tools/forge_novel_manga_batch.py` に、Markdown 入力と並行して YAML 入力を追加する。

推奨:

- 既定は当面 Markdown のまま維持する。
- `--source yaml` または `--ir` を明示したときだけ YAML を読む。
- 互換性が十分に取れた後、YAML を既定候補へ昇格する。

## Phase 5: 品質ゲートの自動化

YAML 構造を使って、次を機械チェックする。

- 各コマに `subjects[]` がある。
- 人物 subject には `character_id` がある。
- `text.dialogue[]` には `speaker` がある。
- ページ全体か各コマにレイアウト情報がある。
- `character_id` 参照が `tag/characters/*.yaml` に存在する。
- キャラクター固定タグが登場コマへ注入される。

## 保留事項

- Pydantic v2 / PyYAML / pytest は現環境に未導入の場合があるため、正式ツール化時に依存管理を決める。
- 既存の `_how_to/tag.md` / `_how_to/manga.md` / `_how_to/manga_tag.md` も、将来的には YAML 正本前提の説明を `_how_to.example/` から更新する。
