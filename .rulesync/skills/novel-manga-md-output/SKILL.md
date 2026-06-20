---
name: novel-manga-md-output
description: >-
  漫画互換 manga/manga_XX.md をチャットや Write だけで書かず、
  manga/pages/*.yaml を正本として novel_prompt_ir_export_md.py で必ず出力する。
  「互換 MD 更新完了」の定義（export 実行＋Read 確認）は本スキルで固定する。
  「これからエクスポートします」と述べたら宣言のみで終えず同一ターンでツール実行まで進める。
targets: ["*"]
---

## 目的

**漫画ページの編集正本は `manga/pages/*.yaml`** とする。`manga/manga_XX.md` は **YAML から機械エクスポートする互換副本**であり、モデルが **会話や Write だけで Step1/Step2 を組み立てる**と、タグ欠落・Step2 不足・【固定見た目】なしなどの簡略版になりやすい。

横断正本は **`.rulesync/rules/concepts.md`** の「漫画IRと互換Markdown」「漫画互換Markdownの完了条件」。本スキルは、その完了条件を満たすための実行手順を定める。

## 互換 MD「更新完了」の定義

ユーザーに「互換 Markdown を出した」「`manga_01.md` を更新した」「エクスポートした」などと **完了扱い**で伝えてよいのは、次をすべて満たしたときに限る。

1. **YAML 正本**: 対象章の `manga/pages/manga_XX_pYY.yaml` が存在し、直前の改稿内容が反映されている。
2. **検証**: `python tools/novel_prompt_ir_validate.py novels/<作品>` を実行済み（推奨: `--strict-quality`）。`character_snapshots` 不足の警告があるときは、先に `python tools/novel_prompt_ir_embed_snapshots.py novels/<作品>` を実行する。
3. **エクスポート**: `python tools/novel_prompt_ir_export_md.py` で **`--output-dir` に作品フォルダ**を渡し、`manga/manga_XX.md` を生成する（下記コマンド例）。漫画を含むときは **`--novelai-pipe-tags` を必ず付ける**。
4. **事実確認**: エクスポート直後に **`Read`** で `manga/manga_XX.md` を確認する。最低限、次があること。
   - `<!-- manga-prompt-ir互換ヘッダ`
   - `## IR正本` と、今回の `--manga-page` に列挙した YAML パス
   - 各ページに `### Step1`（全コマの `- **tag**：`）と `### Step2`（コマ数と同数の `- コマ` 行。多くは `【固定見た目】` 付き）
5. **報告**: 確認 **後** に、`manga/manga_XX.md` と `manga/pages/` の対象 YAML をパスで明示する。

**禁止**: 上記 3→4 を満たす前に、互換 MD の更新完了をユーザーに告げない。チャットへの Step1/Step2 全文貼り付けだけでは **未完了**。

## エクスポートコマンド（既定）

リポジトリルートで実行する。章の全ページは **1回**に列挙する。

```bash
python tools/novel_prompt_ir_embed_snapshots.py novels/<作品>
python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality
python tools/novel_prompt_ir_export_md.py \
  --manga-page novels/<作品>/manga/pages/manga_01_p01.yaml \
  --manga-page novels/<作品>/manga/pages/manga_01_p02.yaml \
  --output-dir novels/<作品> \
  --manga-stem manga_01 \
  --novelai-pipe-tags \
  --no-character-output
```

- `--output-dir` は **`novels/<作品>/`**（`novels/<作品>/manga` ではない）。
- キャラ互換 `tag/<romaji>.md` も同時に要るときは `--no-character-output` を外し、`--character` を追加する。
- Step2 自動言い換えが要るときだけ `--step2-paraphrase`（既定はオフ）。

## ツール予告と応答の継続

「互換 Markdown をエクスポートします」「`manga_01.md` を出します」と述べたら、**同一ターン内**で可能な限り **検証 → `novel_prompt_ir_export_md.py` → `Read`** まで進める。宣言だけで終えない。

- **例外（画像生成）**: `image_provider_novel_manga_batch.py` 等はスキル **`image-provider（旧 forge-txt2img）`** に従い、`--dry-run` 提示までで一度止める。

## 手書き修正したとき

`manga/manga_XX.md` を人間またはエージェントが直接直した場合は、**対応する `manga/pages/*.yaml` に内容を戻してから**再エクスポートする。Markdown を唯一の正本として増殖させない。

## 関連

- `--novelai-pipe-tags` フラグの規則（なぜ付けるか）: `.rulesync/skills/manga-prompt-ir/SKILL.md` の「`--novelai-pipe-tags` の規則」
- 品質点検: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作: `docs/image-generation/manga-prompt-ir.md`
