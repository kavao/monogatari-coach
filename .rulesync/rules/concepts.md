---
targets: ["*"]
description: "Monogatari Coach の横断概念正本"
globs: ["**/*"]
---

# 概念正本

このファイルは、複数のルール・スキル・docs にまたがる概念の短い正本を置く。
長い例、コマンド、provider 別の詳細、トラブルシュートは `docs/` へ置く。

## 自己発展型ルールガバナンス

定義:
**正本（Policy-as-Code）**を短い概念として固定し、**指示（Instruction-driven）**で運用を拡張しつつ、**機械検証**と**追記ログ**で「完了」を拘束して、再現可能に発展する運用方式。

## 正本と副本

定義:
正本は、判断・編集・検証の基準になる一次情報である。副本は、人間の確認、既存バッチ連携、入口生成物、表示用に使う派生情報である。

必須:

- 正本を更新できる状態では、副本だけを直接直して完了扱いしない。
- 副本を直した場合は、対応する正本へ反映してから再生成・再エクスポートする。
- どちらが正本か迷う領域では、作業前に既存ルール・スキルの「正本」節を確認する。

代表例:

| 領域 | 正本 | 副本・派生 |
|------|------|------------|
| ルール・スキル | `.rulesync/rules/`, `.rulesync/skills/` | `AGENTS.md`, `CLAUDE.md` |
| 創作技法雛形 | `_how_to.example/` | `_how_to/` のユーザー調整 |
| 操作説明 | `docs/` | チャット上の要約 |
| 小説本文 | `novels/<作品>/_novel_text/novel_text*.md` | チャット上の本文提示 |
| 書評・興味判定 | `novels/<作品>/_reader/*.md` | チャット上の要約 |
| キャラクタータグ | `novels/<作品>/tag/characters/*.yaml` | `tag/<romaji>.md` |
| 漫画ページ | `novels/<作品>/manga/pages/*.yaml` | `manga/manga_XX.md` |
| 挿絵計画 | `novels/<作品>/illustrations/plans/*.md` | `_meta.md` §3.2 章別割当表 |
| 挿絵ページ | `novels/<作品>/illustrations/pages/*.yaml` | `illustrations/illustration_XX.md` |

## NovelAI 向けタグ分離（パイプ区切り）

定義:
NovelAI での生成において、画風・品質タグ（ベース）とキャラクター固有タグを分離し、一貫性を高めるための形式である。

必須:

- 互換Markdown（`tag/*.md`, `manga_XX.md`）のタグ行では、`ベースタグ | キャラクタータグ` の形式を標準とする。
- `novel_prompt_ir_export_md.py` でエクスポートする際は、原則として `--novelai-pipe-tags` を付与する。
- パイプ `|` の前後はカンマ区切りとし、キャラクター固有の特徴（髪、目、衣装など）を後半に配置する。

参照:

- Markdown 互換層: `.rulesync/skills/novel-tag-md-format/SKILL.md`
- 漫画 IR: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- ルール作成規約: `.rulesync/rules/rule-authoring.md`

## Tag Mode バリアント階層（000番台・100番台）

定義:
キャラクタータグの `prompt_variants` は **000番台（服装・衣装状態）** と **100番台（資料・ポーズ・紹介シート）** に分ける。漫画の `subjects[].variant_id` に使うのは **000番台のみ**（例: `001_normal`）。

必須:

- Tag Mode 完了時は、主要キャラごとに **`000_base`**（固定外見）と **000番台**（作品に必要な衣装状態）を `tag/characters/*.yaml` に書く。
- **`000_base.danbooru_tags` に性別・人数（`1boy` / `1girl` / `solo` 等）を含める**。ルートの **`character_tags` フィールドは 2026-06 以降廃止**（移行: `tools/novel_prompt_ir_migrate_character_tags.py`）。
- **`000_base` は必須**（`novel_prompt_ir_validate.py` で欠落・空は ERROR）。
- **汎用100番台**（次節「汎用テンプレート」）は Tag Mode の標準成果物とする。
- **カスタム要素**（次節）は作品メタまたはユーザー指示に列挙したときだけ追加する。
- 100番を省略するときは当該バリアントの `description` または作品 `_meta.md` のキャラタグ方針に **省略理由**を残す。
- 100番台は **`combines_with`** で000番台の `variant_id` を指定する。互換 MD 出力は `novel_prompt_ir_export_md.py --novelai-pipe-tags` を用いる。

禁止:

- 000番台のみ作成して Tag Mode 完了扱いにしない（汎用100番を省略するときは理由を明示する）。
- 漫画 `variant_id` に `100_*` を指定しない。
- **`000_base`** および **固定合成経路**（次節「身体的正本」§3.1）へ **露出・性器・裸限定**の Danbooru タグを置かない。

参照:

- 身体的正本（3階層）: 本ファイル「Tag Mode 身体的正本（3階層継承）」
- 汎用／カスタムの正本: 本ファイル「Tag Mode 汎用テンプレートとカスタム要素」
- 入口ルール: `.rulesync/rules/overview.md` §2.2.1
- 型・手順: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- 人間向け操作: `docs/workflow/instruction-driven.md`「G. キャラクター画像タグ」

## Tag Mode 身体的正本（3階層継承）

定義:
露出誘発タグを着衣バリアントから物理的に隔離する **SFW 固定 → 身体的正本（NSFW）→ 状況継承** の標準構造。000番台・100番台の帯分け（前節）に加え、**タグの注入経路**を次の3階層で固定する。

| 階層 | 定義名 | 必須条件 |
|------|--------|----------|
| **Level 1** | **固定外見（SFW）** | `000_base` は髪・目・肌・種族・固定小物など**服の上から不変**の特徴のみ。**露出・性器タグは原則禁止**。 |
| **Level 2** | **身体的正本（NSFW）** | **`006_nude`**（代表 ID）を裸の標準とし、`nude` および性器・秘部の詳細タグを**ここに集約**。NSFW を扱う作品でのみ必須（全年齢作品は省略可。省略理由を `description` または `_meta.md` に残す）。 |
| **Level 3** | **状況バリアント** | 裸を伴う状況は **`combines_with: 006_nude`**（または当該作品の身体的正本 ID）を必須とし、Level 2 を継承する。000番台 ID のまま付けてよい（漫画 `variant_id` 互換）。 |

### 固定合成経路の禁止事項（Level 1 と同格）

`appearance.distinctive_features` および `manga_rules.consistency_tags` は、漫画 batch の**主経路**（`character_ir_tags()`・`subjects[].variant_id` 指定時）では **`000_base` 優先のため合成されない**。一方 **副経路**（variant 未指定、`novel_prompt_ir_embed_snapshots`、`prompt_renderer` 等）では**状況に関係なく注入され得る**。いずれにせよ `000_base` と同様、次を **原則禁止**する。

- 性器・秘部の形状・状態タグ（裸／局部でないと意味が出ない Danbooru トークン）
- `nude` および局部を直接示すタグ

入れてよい例: 大きな手、敏感肌、翅なしなど**着衣時も成立する**特徴。身体的詳細のタグ列正本は **`006_nude` の `danbooru_tags`**（Level 2）。`character.md` に記述があっても、**生成タグとしては Level 2 にのみ**載せる。

必須:

- Tag Mode（NSFW 作品）では **`000_base` → 000番台（着衣）→ `006_nude`（該当時）→ 100番台** の順で `prompt_variants` を組み立てる。
- Level 3 の `combines_with` は、キャラ画像バッチと漫画バッチの両方で解決される（`tools/image_provider_novel_manga_batch.character_ir_tags` は `000_base` 優先＋`combines_with` 解決に揃える）。

禁止:

- 000番台（`001_normal` 等）の `danbooru_tags` に **裸露・性器タグを直接書く**（半脱衣装タグのみの `005_half_dressed` 等は除く）。裸露本体は **`006_nude` 経由**。
- `distinctive_features` / `consistency_tags` に **裸限定タグ**を置き、着衣コマへの漏洩経路を残す。

参照:

- 創作技法: `_how_to.example/tag.md`「身体的正本（3階層）」
- 検証: `tools/novel_prompt_ir_validate.py`（身体的正本ルールの WARNING / `--strict-quality`）

## Tag Mode 汎用テンプレートとカスタム要素

定義:

- **汎用テンプレート**: リポジトリ共通で、作品ジャンルに依存しない **固定の `variant_id` 集合**。本節の表が正本である。`_how_to/` の見出し・ファイル構成に依存しない。
- **カスタム要素**: **当該作品だけ**に必要な `prompt_variants`（特殊衣装、特殊資料ポーズ、ジャンル固有の局部・行為タグなど）。共有ルールでは **ID 名・部位・行為を固定しない**。採用は **作品 `_meta.md` のキャラタグ方針**（次節）またはユーザーの明示指示のみ。

分離の原則:

- エージェントは **汎用テンプレートを先に揃え**、カスタムは **列挙された分だけ**追加する。
- `_how_to/`（ユーザー調整の創作技法）の有無や章立てで、カスタムの要否や ID を推測しない。
- 他作品で使った `variant_id` を、別作品の共有必須としてコピーしない。

### 汎用テンプレート（正本一覧）

| 帯 | 必須 `variant_id`（代表） | 用途 |
|----|---------------------------|------|
| 固定基礎 | `000_base` | 髪・目・肌・種族・固定小物（衣装・姿勢・背景なし） |
| 000番台 | `001_normal` ほか | 衣装状態。漫画 `variant_id` に使う。**作品 `_meta.md` §4（漫画 variant 表）に載る ID はすべて YAML に存在させる** |
| 100番台 | `100_intro`, `101_turnaround`, `102_signature_pose` | 紹介・三面図・決めポーズの資料。`combines_with` 必須（平服資料は多くの作品で `001_normal`） |

000番台の追加は、**§4 の表・`character.md`・プロット**に登場する衣装に合わせる。水着・戦闘服・半脱等は作品ごとに ID を振る。**身体的正本**は多くの NSFW 作品で **`006_nude`**（前節 Level 2）。裸露タグは 000番台の着衣スロットではなく **`006_nude` に集約**する。

### カスタム要素（作品ごと）

| 項目 | 内容 |
|------|------|
| 正本 | 作品 `novels/<作品>/_meta.md` の **キャラタグ方針** 節（フィールド定義は次節） |
| 列挙 | キャラごとに `variant_id`（任意で `combines_with`・短い見出し） |
| 抽象例（IDは作品が命名） | 資料・局部を見せるポーズ（100番）、資料・接触ポーズ（100番）、ケア・治療用衣装（000番） |
| 語彙 | Danbooru 具体タグは **`character.md`** と作品 YAML。共有ルールに部位名・固定IDを書かない |

**テンプレート一式モードでも、カスタムは自動追加しない**（キャラタグ方針に列挙した分のみ）。

## Tag Mode 作品メタ（キャラタグ方針）

定義:
作品 `novels/<作品>/_meta.md` の **「画像・漫画生成設定」** 内に置く、Tag Mode の方針メモ。節番号（例: §6）は `_how_to.example/meta.md` と揃えてよいが、**ルール上の必須フィールドは本節**を正とする（`_how_to` の構造に依存しない）。

| フィールド | 値の例 | 意味 |
|------------|--------|------|
| **バリアント方針** | `標準` / `テンプレート一式` / `最小` | 省略の厳しさ（本ファイル「テンプレート一式」参照） |
| **カスタム要素** | キャラ別の `variant_id` リスト | 汎用外。空ならカスタムなし |
| **除外** | `variant_id` リスト | ユーザーが明示した除外のみ |

エージェントは Tag Mode 開始時に **当該作品の `_meta.md`** を読み、上記フィールドがあればそれに従う。

## Tag Mode テンプレート一式（裁量を抑える）

定義:
本ファイル **「Tag Mode 汎用テンプレート」** に列挙した `variant_id` を、エージェントの独自判断で省略せず YAML に書く Tag Mode の指示モード。カスタム要素は **作品メタに列挙された分のみ**追加する。

トリガー（いずれかで発動）:

- チャット: 「**テンプレート分はすべて作成**」「**標準テンプレート一式**」「**Tag Mode（テンプレート一式）**」「**tag テンプレ完備**」
- 作品 `_meta.md` の **バリアント方針** が **`テンプレート一式`**
- overview §2.2.1 の「テンプレート一式」指示文テンプレ

必須（主要キャラごと）:

1. **汎用テンプレート**（`000_base`、`100_intro` / `101_turnaround` / `102_signature_pose`、`combines_with` 付き）。
2. **000番台**: 作品 `_meta.md` §4（漫画 variant 対応）の **`variant_id` をすべて** `tag/characters/*.yaml` に存在させる。
3. **カスタム要素**: 作品メタの **カスタム要素** に列挙した `variant_id` をすべて作る（テンプレート一式だけでは作らない）。
4. エクスポートは **`novel_prompt_ir_export_md.py --novelai-pipe-tags`**。

禁止（テンプレート一式モード時）:

- エージェントが独断で **汎用100（100〜102）** を省略すること（**除外** に列挙された ID のみ省略可）。
- 共有ルールに **ジャンル固有の固定 `variant_id`** を必須と書くこと。
- テンプレート一式と標準の省略規則が矛盾するときは、**直近のユーザー指示**と **作品 `_meta.md` のキャラタグ方針** を優先し、一言確認する。

参照:

- 汎用／カスタムの定義: 本ファイル「Tag Mode 汎用テンプレートとカスタム要素」「Tag Mode 作品メタ」
- 入口ルール: `.rulesync/rules/overview.md` §2.2.1

## 漫画IRと互換Markdown

定義:
漫画ページ・キャラクタータグの編集正本は YAML IR であり、`tag/<romaji>.md` と `manga/manga_XX.md` は YAML から出力する人間向け・既存バッチ向けの互換Markdownである。

必須:

- キャラクタータグの正本は `novels/<作品>/tag/characters/<character_id>.yaml` とする。
- 漫画ページの正本は `novels/<作品>/manga/pages/manga_XX_pYY.yaml` とする。
- 互換Markdownを手で直した場合は、対応する YAML IR へ戻してから再エクスポートする。
- Manga Tag Mode の初手として、`manga/manga_XX.md` だけを直接新規作成して唯一の正本にしない。
- 画像生成前の検証は YAML IR を中心に行い、必要に応じて互換Markdownを生成直前の確認先として使う。

役割:

| ファイル | 役割 |
|----------|------|
| `tools/manga_prompt_ir/schemas/*.py` | 型・必須項目の正本 |
| `tag/characters/*.yaml` | キャラクター外見・衣装・固定タグの編集正本 |
| `manga/pages/*.yaml` | ページ・コマ・人物・セリフ・構図の編集正本 |
| `tag/<romaji>.md` | キャラクタータグの可読副本・既存バッチ互換 |
| `manga/manga_XX.md` | 漫画 Step1 / Step2 の可読副本・既存バッチ互換 |

参照:

- Manga Prompt IR: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- Manga Tag 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`, `docs/image-generation/manga-tag-generation.md`

## 漫画互換Markdownの完了条件

定義:
`novels/<作品>/manga/manga_XX.md`（Step1 / Step2 の互換副本）を新規作成・更新したと報告してよいのは、**`tools/novel_prompt_ir_export_md.py` が書き出したファイル**であり、チャットやエージェントの **Write だけで Step1/Step2 全文を組み立てた状態**ではない。

必須:

- YAML IR 正本（`manga/pages/*.yaml`）を更新してからエクスポートする。
- `tools/novel_prompt_ir_validate.py` で検証し、`tools/novel_prompt_ir_export_md.py` でエクスポートする。
- エクスポート直後に `Read` でヘッダ・IR正本・Step1/Step2 の構造を確認してから完了報告する。
- 更新パス（`manga/manga_XX.md`）と IR 正本の YAML パスを添えて完了を伝える。

禁止:

- チャットや Write だけで `manga/manga_XX.md` を新規・全面更新して互換出力完了としない。
- YAML を更新しないまま互換 Markdown だけを直して Manga Tag Mode を完了扱いにしない。
- `novel_prompt_ir_export_md.py` の実行と `Read` による確認の前に「エクスポートした」と述べない。

参照:

- 実行手順（コマンド・フラグ詳細）: `.rulesync/skills/novel-manga-md-output/SKILL.md`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`

## Manga Tag Mode ワークフロー

定義:
Manga Tag Mode は、小説本文とキャラクター正本から漫画ページ YAML IR を作り、検証し、必要に応じて互換Markdownや画像生成へ進める作業である。

必須:

1. 本文正本とキャラクター正本を確認する。
2. 作品 `_meta.md` の §4（TPO → variant 対応表）と §5（漫画タグ層）を区間ごとに合意する（書き方は `_how_to.example/meta.md` を正とする）。
3. `manga/pages/*.yaml` を作成・更新する（§5 常時タグの転記漏れには `tools/novel_manga_apply_tag_defaults.py --apply` を使う）。`panels[].summary` があるコマは **「Manga `summary_en` の翻訳経路」** に従い `summary_en` + `summary_en_source` を揃える。
4. 品質ゲートで確認し、`tools/novel_prompt_ir_validate.py`（本番前は `--strict-quality`）で検証する。
5. 互換 Markdown が必要なときだけ `tools/novel_prompt_ir_export_md.py` で再エクスポートする。
6. 画像生成は「画像生成: dry-run から本番まで」に従う。

禁止:

- 互換 Markdown だけを新規作成・修正して Manga Tag Mode 完了扱いにしない。
- 生成前検証を YAML IR ではなく、互換 Markdown だけで済ませない。

参照:

- 詳細手順: `.rulesync/skills/manga-prompt-ir/SKILL.md`
- 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`

## Manga `summary_en` の翻訳経路

定義:
漫画ページ IR の `panels[].summary`（日本語・編集用）に対応する英語1文 `panels[].summary_en` の付与方法。`location_en` / `pose_action_en` 等と同様、**エージェントが YAML 保存時に英語行を埋める**のを主経路とする。`summary_en_source` は翻訳時点の `summary` 原文を記録し、鮮度追跡の正本とする。

必須（主経路）:

1. `summary` を書いたコマでは、同ターンで **`summary_en`（英語1文）** と **`summary_en_source`（= そのときの `summary` 原文）** を YAML に書く。
2. `python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality` で検証し、**exit 0** を `summary_en` 完了の機械判定とする（欠落・CJK・鮮度不一致はエラー）。
3. `summary` のみ直したときは **`summary_en` も更新**するか、validate の鮮度エラーに従って直す。

任意（従経路）:

- `python tools/novel_manga_panel_summary_en.py novels/<作品>` — エージェントなし編集・一括再翻訳・CI 向け。`.env` の `MONOCRI_SUMMARY_EN_*` と Chat API キーが必要。**Manga Tag Mode 完了の前提にはしない**。

省略:

- NovelAI コマ生成で `summary_en` を載せないときは `MONOCRI_MANGA_STEP1_INCLUDE_PANEL_SUMMARY=0` または `--no-include-panel-summary`。`--strict-quality` で `summary_en` を必須にするかは作品運用で決める（省略時は作品 `_meta.md` に理由を残す運用可）。

禁止:

- `OPENAI_API_KEY` 未設定を理由に Manga Tag Mode 全体を止める扱いにしない（翻訳ツール未実行は主経路ではブロッカーではない）。
- エディタでの漫然たる英語入力（`summary_en_source` なし・validate 未確認）で完了扱いにしない。

参照:

- スキル: `.rulesync/skills/manga-prompt-ir/SKILL.md`（`panels[].summary_en` 節）
- 検証実装: `tools/manga_prompt_ir/summary_en.py` の `summary_en_quality_issues`
- 操作説明: `docs/image-generation/manga-prompt-ir.md`（`summary_en` 節）

## 挿絵計画（Illustration Plan Mode）

定義:
挿絵計画は、本文執筆後・YAML IR 作成前に行う **Step 1**。章ごとに 0枚／1枚／複数枚を決め、候補3点・採用・本文アンカー・衣装 variant を計画 MD に記録する。表紙（`illustration_00` 帯）は章挿絵とは**別枠**として管理する。

必須:

- 挿絵計画の正本は `novels/<作品>/illustrations/plans/` 配下の Markdown とする（表紙: `cover_plan.md`、章: `chapter_plan.md`）。
- **`_meta.md` §3.2 章別割当表**が章ごとの枚数・位置の正本。YAML より先に §3.2 を更新する。
- 計画 MD を経由せず YAML だけを作成して Illustration Tag Mode を完了扱いにしない。
- 章が 0枚のとき: YAML を作らない。計画 MD に「0枚＋理由」を書いた状態が Step 1 の完了条件。
- 表紙は §3.2 章別割当表に載せない（§3.1 と `cover_plan.md` で独立管理）。

参照:

- 創作技法雛形: `_how_to.example/illustration_plan.md`
- Illustration Plan スキル: `.rulesync/skills/illustration-plan/SKILL.md`

## 挿絵IR

定義:
挿絵IRは、小説本文から漫画ではない一枚絵・章扉・表紙などを作るための YAML IR である（**Step 2**）。型は漫画ページIRと同じ `MangaPagePrompt` を使い、`meta.intent: illustration` で用途を区別する。**計画 MD（Step 1）で採用が確定した IR だけ**作成する。

必須:

- 挿絵ページの正本は `novels/<作品>/illustrations/pages/illustration_XX_pYY.yaml` とする。
- Illustration Tag Mode 開始前に必ず `_meta.md` §3.2 と `illustrations/plans/chapter_plan.md`（または `cover_plan.md`）を読む。
- `panels[]` は漫画のコマではなく、構図を分解する構成セルとして扱う。単体挿絵は1セル、群像・複合構図は複数セルを許容する（複合構図の判断・生成方針は **`.rulesync/rules/overview.md`** の Illustration Tag Mode）。
- 既定は枠線なし・パネル境界なしの一枚絵とし、枠を使う場合は `manga.panel_layout` または `render_instruction.user_directives.page_notes` に意図を明記する。
- セリフ・効果音などの `text` は原則空にする。画像内文字が必要な場合だけ理由と配置を明記する。
- 画像保存先は `novels/<作品>/illustrations/_assets/illustration_XX/` とする。
- 検証は `tools/novel_prompt_ir_validate.py` で行い、画像生成は dry-run から本番までの手順に従う。

禁止:

- 計画 MD（Step 1）を経由せず YAML だけを新規作成して Illustration Tag Mode を完了扱いにしない。
- 章が 0枚と決まっている場合に YAML を作成しない。

役割:

| ファイル | 役割 |
|----------|------|
| `_meta.md` §3〜§3.2 | 方針・表紙・章別割当の正本 |
| `illustrations/plans/cover_plan.md` | 表紙計画の正本（Step 1） |
| `illustrations/plans/chapter_plan.md` | 章挿絵計画の正本（Step 1） |
| `illustrations/pages/*.yaml` | 挿絵・表紙の実行正本（Step 2） |
| `illustrations/_assets/<illustration_XX>/` | 挿絵・表紙画像の保存先 |
| `illustrations/illustration_XX.md` | 任意の可読副本・外部連携用 |

参照:

- Illustration Plan スキル: `.rulesync/skills/illustration-plan/SKILL.md`
- Illustration Prompt IR: `.rulesync/skills/illustration-prompt-ir/SKILL.md`
- 操作説明: `docs/image-generation/illustration-prompt-ir.md`

## Illustration Tag Mode 作品メタ（挿絵・表紙）

定義:
作品 `novels/<作品>/_meta.md` の **「III. 画像・漫画生成設定」§3〜§3.2** に置く、挿絵専用の方針メモ。漫画の §4 variant 表・§5 タグ層と同型の責務分離で管理する。

| 節 | 内容 |
|----|------|
| **§3 方針** | 挿絵密度方針・章あたり既定枚数・1枚時の既定位置・候補数・優先場面・除外条件・計画正本パス・IR 番号設計 |
| **§3.1 表紙** | 表紙の有無・比率・計画正本・採用IR・計画状態（別枠・§3.2 に混在させない） |
| **§3.2 章別割当表** | 章ごとの 0/1/multiple・位置・優先シーン・計画／YAML／生成の進捗状態 |

必須:

- Illustration Plan Mode 開始時に必ず `_meta.md` §3〜§3.2 を読む。
- §3.2 の「枚数」列が章ごとの 0/1/multiple の正本。計画 MD と矛盾するときは、**直近のユーザー指示 → §3.2 表 → §3 方針フィールド** の順で優先する。
- 表紙は §3.1 と `cover_plan.md` で管理し、§3.2 の表には載せない。
- フィールド定義の詳細は `_how_to.example/meta.md` §3〜§3.2 を参照する。

## 画像保存先

定義:
生成画像は、作品フォルダ内の用途別ディレクトリに保存し、後から本文・タグ・漫画ページと対応を追える状態にする。

必須:

- キャラクター画像は `novels/<作品>/tag/<romaji>/` に保存する。
- 漫画ページ・コマ画像は `novels/<作品>/manga/_assets/<manga_XX>/comic/` に保存する。
- 漫画の背景資料画像は `novels/<作品>/manga/_assets/<manga_XX>/backgrounds/` に保存する。
- 挿絵・表紙画像は `novels/<作品>/illustrations/_assets/<illustration_XX>/` に保存する。
- コマ画像はファイル名接頭辞でページ・コマを区別する。例: `manga_01_p02_k03`。
- ページ単位サブフォルダ（`p01/`, `p02/` など）は既定・推奨にしない。必要な場合だけ任意で使う。

参照:

- 画像レイアウト: `.rulesync/skills/novel-image-layout/SKILL.md`
- 画像生成: `.rulesync/skills/forge-txt2img/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## `_how_to/` と `docs/`

定義:
`_how_to/` は創作技法を扱う準ルール領域であり、`docs/` は人間向けの操作マニュアルである。

必須:

- ツールの操作手順、コマンド例、provider 設定は `docs/` に置く。
- 小説文法、漫画作法、タグ語彙、書評観点は `_how_to.example/` またはユーザー調整領域の `_how_to/` に置く。
- LLM が `_how_to/` を恒久的に更新するのは、ユーザーが明示した場合に限る。

参照:

- docs 記述ルール: `.rulesync/rules/docs-writing.md`
- `_how_to/` の説明: `docs/project-structure/how-to-area.md`

## 共有ツールとユーザ用 Python（`tools/` と `_how_to/tools/`）

定義:
リポジトリ直下の **`tools/`** は**共有・正規運用**の公式スクリプトの置き場である。**`_how_to/tools/`** は **`_how_to/skills/` に付随するユーザワークフロー**用の Python を置く領域であり、ユーザーが保守する。

必須:

- **`.rulesync/skills/<skill_name>/` には Python を置かない**（`SKILL.md`・`MIGRATION.md` など Markdown のみ）。公式スキルが Python を要するときは **`tools/`** に実装する。
- **`_how_to/skills/<名前>/SKILL.md`** とセットで動かす**個人・試行ワークフロー固有の変換・補助スクリプト**は **`_how_to/tools/`** に置く。`SKILL.md` からは `_how_to/tools/<script>.py` を参照してよい。
- **`_how_to/tools/` のスクリプトをリポジトリ全体の既定前提として扱わない**。CI・必須チェック・全作品共通の手順に組み込む場合は、意図を整理したうえで **`tools/`** へ昇格するか、公式スキルとして再配置する。
- **短命の試行**は引き続き **`tools_temp/`** を使う（`_how_to/tools/` は、運用上わりと長く残すユーザスクリプト向け）。

参照:

- ローカル試行: ルート `readme.md` の「ローカル試行用」、`tools_temp/README.md`
- 入口ルールの詳細: `.rulesync/rules/overview.md` の「スキルへの Python 追加ルール」「`_how_to/tools/`（ユーザ用 Python）」

## 画像生成: dry-run から本番まで

定義:
画像生成は、課金・画風・保存先・provider 差異を伴うため、必ず計画確認を挟む。

必須:

1. `.env` と `config/image_generation.json` で provider と設定を確認する。
2. `--dry-run` で provider、モデル、ジョブ数、保存先を確認する。
3. dry-run 結果をユーザーに提示し、明示承認を得る。
4. 承認後にのみ `--dry-run` なしで本番実行する。
5. 本番後、dry-run で示した保存先に画像ファイルが存在することを確認してから完了報告する。

禁止:

- dry-run の提示前に本番実行しない。
- ユーザー承認前に「続けて本番まで」進めない。
- 保存先のファイル確認前に「生成完了」と言わない。

参照:

- 画像生成スキル: `.rulesync/skills/forge-txt2img/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## 画像生成失敗時の provider 切替

定義:
dry-run 承認は、その provider と設定で実行する承認であり、別 provider への自動切替承認ではない。

必須:

- HTTP 429 / 403 / 5xx などで失敗した場合は、provider 名、エラー、対象ジョブまたは範囲を報告する。
- 待つ、provider を変える、範囲を絞るなどの選択肢を提示し、ユーザーの明示指示を待つ。

禁止:

- 別 provider へ自動で切り替えて再実行しない。
- 失敗した provider の承認を、別 provider の本番承認として扱わない。

参照:

- 画像生成スキル: `.rulesync/skills/forge-txt2img/SKILL.md`

## 完了扱い条件

定義:
「完了」は、成果物が正本または保存先に実在し、確認が済んだ状態だけを指す。

執筆:

- 正本 `novels/<作品>/_novel_text/novel_text*.md` に書き込む。
- 書き込み後、再読込または `tools/novel_char_count.py` で確認する。
- 確認後に、更新ファイルパスを添えて完了報告する。
- チャットに本文を出しただけでは完了ではない。

画像生成:

- ユーザー承認後に本番実行する。
- dry-run で示した保存先に画像ファイルが存在することを確認する。
- 確認後に、保存先を添えて完了報告する。

漫画互換Markdown（`manga/manga_XX.md`）:

- `tools/novel_prompt_ir_export_md.py` で出力する（詳細は上記「漫画互換Markdownの完了条件」）。
- エクスポート後に `Read` でヘッダ・IR正本・Step1/Step2 の構造を確認する。
- チャットや Write だけで互換 MD を書いた状態では完了ではない。

参照:

- 本文出力: `.rulesync/skills/novel-text-file-output/SKILL.md`
- 漫画互換 Markdown: `.rulesync/skills/novel-manga-md-output/SKILL.md`
- 清書出力: `.rulesync/skills/novel-refinement-output/SKILL.md`
- 画像生成: `.rulesync/skills/forge-txt2img/SKILL.md`

## 評価出力の保存先

定義:
下読み・書評・一般読者の興味判定は、チャット上の感想ではなく、作品フォルダの `_reader/` に保存した評価ファイルを正本とする。**First Reader は足切りゲートであり**、G1（冒頭）／G2（章完）／G3（全文）の3段階で運用する。

必須:

- First Reader の書評は `novels/<作品>/_reader/YYYYMMDD_HHMM.md` に保存する。
- Interest Check の結果は `novels/<作品>/_reader/interest_YYYYMMDD.md` に保存する。
- チャットには判定、短い理由、改善ポイントの要約だけを返す。
- 書評観点は `_how_to/reader.md`、興味判定のペルソナ・第一印象は `_how_to/standard_reader.md` を参照する。
- 保存したファイルパスをチャットで明示してから完了扱いにする。
- **足切り判定は100点閾値を優先する**（70点以上: 読むべき / 55〜69点: 強い美点1つ以上なら読むべき / 54点以下: 読まなくていい）。閾値の定義と6項目の配点は `_how_to.example/reader.md` を参照する。
- **ゲート段階（G1/G2/G3）によってファイル名を変えない**。`_reader/YYYYMMDD_HHMM.md` を足切り・下読み兼用とし、段階はファイル内のヘッダに明記する。

禁止:

- チャットに書評本文を出しただけで、評価完了としない。
- `_workingspace/log/` を作品ごとの書評本文の保存先にしない。査証ログには作業事実だけを追記する。
- 5段階評価だけを根拠に足切り判定を行わない（100点換算で閾値を確認してから判定する）。

参照:

- 評価出力スキル: `.rulesync/skills/novel-reader-output/SKILL.md`
- 操作説明: `docs/workflow/reader-output.md`、`docs/workflow/instruction-driven.md`

## 評価ファイル命名と役割（全モード一覧）

定義:
評価モードごとに異なるファイル名を使い、保存先と完了条件を `_reader/` に統一する。

| モード | 技法正本 | ファイル名 | 100点の意味 | 典型タイミング |
|--------|----------|-----------|-------------|----------------|
| First Reader（足切り） | `_how_to/reader.md` | `_reader/YYYYMMDD_HHMM.md` | 6項目100点（足切り用） | G1冒頭/G2章完/G3全文 |
| Interest Check | `_how_to/standard_reader.md` | `_reader/interest_YYYYMMDD.md` | なし（合格/不合格） | 企画・第1章・投稿前 |
| Editor Score | `_how_to/editor_score.md`（予定） | `_reader/score_YYYYMMDD_HHMM.md` | 5項目100点（深掘り用） | 足切り通過後・推敲後 |
| Consistency Audit | `_how_to/consistency_audit.md`（予定） | `_reader/consistency_YYYYMMDD.md` | なし（表形式） | 複数章完成後 |
| Synopsis（前処理） | `_how_to/novel_synopsis_for_review.md`（予定） | `_reader/synopsis_YYYYMMDD.md` | なし | 長文G3/Editor Score前 |

必須:

- ファイル名はモードごとに上表を参照し、既存名に勝手に接尾辞を追加しない。
- `_reader/YYYYMMDD_HHMM.md`（First Reader）は足切り・下読み兼用とし、G1/G2/G3 段階によってファイル名を変えない。
- 「予定」技法は対応するファイルが存在するまで、そのモードは実行しない。

参照:

- 保存手順: `.rulesync/skills/novel-reader-output/SKILL.md`
- 深掘り評価手順（予定）: `.rulesync/skills/novel-evaluation-output/SKILL.md`
- 操作説明: `docs/workflow/reader-output.md`

## 足切りと深掘り評価の住み分け

定義:
First Reader（足切り）と Editor Score（深掘り）は配点・目的が異なる別モードであり、混同しない。

| 観点 | First Reader（足切り） | Editor Score（予定・深掘り） |
|------|------------------------|------------------------------|
| 目的 | 読む／読まないの選別 | どこを直すと何点上がるか |
| 技法正本 | `_how_to/reader.md` | `_how_to/editor_score.md`（予定） |
| 配点 | 冒頭20＋キャラ20＋プロット20＋文章15＋わかりやすさ10＋独創15 | 構造20＋キャラ20＋文体20＋世界観20＋完成度20 |
| 閾値 | 70 / 55–69（美点）/ 54 | 点数は参考。致命弱点の優先順位が主 |
| 入力 | 対象章〜全文（短め） | あらすじ＋全文 or 重要章（長文多段） |
| 実行条件 | 任意のタイミング | 足切り通過後を推奨 |

必須:

- 「Editor Score で足切りする」「足切り点数で深掘り改善する」という混用をしない。
- 両モードを同一セッションで行う場合、先に足切り（First Reader）を完了してから Editor Score へ進む。
- ジャンル別編集者ペルソナは、Phase 1 では `config.md` のジャンル参照のみとする（専用 persona ファイルは Phase 2 以降）。

## 長文評価の閾値と前処理

定義:
作品全体（G3）または Editor Score で長文を一括評価することが困難な場合、Synopsis（あらすじ）を先行して作成し、段階的に評価を進める。

必須:

- 作品合計 **30,000字超**、または章単体 **8,000字超** の場合は、G3 全文足切り・Editor Score の前に Synopsis 先行を推奨する（P2 実装後は必須）。
- Synopsis の書式は `_how_to/novel_synopsis_for_review.md`（予定）に従う。ファイルが未作成の間は、400字程度の客観的あらすじをチャット内で作成してから評価を進めてよい。
- 章分割評価（文字数加重平均）の手順は `.rulesync/skills/novel-reader-output/SKILL.md` の「長文 G3 の分割評価」節を参照する。

参照:

- 長文パイプライン手順: `.rulesync/skills/novel-evaluation-output/SKILL.md`「長文多段パイプライン」
- 設計根拠: `_workingspace/plans/20260608_novel-evaluation-enhancement.md` Phase 2

## 評価作業一時領域（`_reader/_work/`）

定義:
30,000字超の長文評価や章分割評価で生じる中間作業ファイル（章別スコアノート・集計メモ等）を置く一時領域。`_reader/` 直下の最終成果物と混在させない。

必須:

- `_reader/_work/<YYYYMMDD>/` を評価セッションの作業フォルダとする（`YYYYMMDD` は評価実施日）。
- **最終成果物のみ** `_reader/` 直下に置く（命名は「評価ファイル命名と役割」の表に従う）。
- 作業フォルダ内の標準ファイル:
  - `ch01_eval.md`〜`chNN_eval.md`: 章ごとのスコアノート
  - `step_b.md`: 構造・プロット・テーマの中間分析（あらすじから）
  - `step_c.md`: 文体・描写の中間分析（章サンプルから）
  - `aggregate.md`: 加重平均計算メモ（計算式: `最終総合点 = Σ(章スコア × 章文字数) ÷ 合計文字数`）
- 作業フォルダのファイルは評価完了後も残してよい（削除はユーザー判断）。

禁止:

- `_reader/_work/` 内のファイルを最終成果物として参照しない。最終点数・判定は `_reader/` 直下のファイルを根拠にする。
- `_reader/` 直下に `ch01_eval.md` 等の章別ノートを直接置かない。

参照:

- 最終成果物の命名: 本ファイル「評価ファイル命名と役割（全モード一覧）」
- 長文多段パイプライン手順: `.rulesync/skills/novel-evaluation-output/SKILL.md`「長文多段パイプライン」

## プロジェクト・インテリジェンス

定義:
`_workingspace/` は、作品本文ではなく、プロジェクト横断の計画・履歴・判断理由を管理する領域である。

役割:

| 領域 | 役割 | 正本性 |
|------|------|--------|
| `_workingspace/plans/` | これから行う作業予定、改修順、チェックリスト | 未来・進行中の計画 |
| `_workingspace/log/YYYYMM.md` | そのセッションで何をしたかの作業事実 | 過去作業の査証 |
| `_workingspace/diary/YYYYMM.md` | 次回以降も効く判断理由、好み、運用知見 | 横断ナレッジ |

必須:

- 実施済みの作業事実は査証ログへ追記する。
- 長期的に参照したい判断理由や運用知見は日記へ追記する。
- 作業計画のチェックだけで完了事実の記録を済ませない。
- 査証ログ・日記は既存行を削除、上書き、並べ替えず、追記で更新する。
- **計画ファイル（`_workingspace/plans/*.md`）には必ず成果物チェックリスト（`- [ ]` / `- [x]` 形式）を含める。** 完了済みのタスクは `- [x]` にし、進捗が一目でわかるようにする。計画ファイルを作成したあとも、完了のたびにチェックを入れて最新状態を保つ。
- **トピック計画のファイル名**は **`YYYYMMDD_<slug>.md`**（作成日8桁＋アンダースコア＋slug）。月次集約 `YYYYMM.md`・`backlog.md`・`README.md` は例外。詳細は **`_workingspace/plans/README.md`**「ファイル命名」を正とする。

参照:

- 査証ログ: `.rulesync/skills/workspace-audit-log/SKILL.md`
- 日記: `.rulesync/skills/workspace-diary/SKILL.md`
- 操作説明: `docs/tools/index.md`, `docs/project-structure/index.md`

## 生成モード用語

定義:
画像生成のモード名は、入力粒度と出力の期待値を区別するために使う。

| 用語 | バッチ source | 意味 |
|------|---------------|------|
| コマ生成 | `step1-panels` | 各コマを独立した画像として生成する |
| 精密ページ生成 | `step1-pages` | Step1 相当の具体情報を使い、ページ全体を生成する |
| ページ生成 | `step2-pages` | Step2 相当の抽象化した配置説明で、ページ全体を生成する |
| 背景資料生成 | `background-concepts` | 人物を主役にせず、場所・光・物品配置の参照画像を生成する |

必須:

- コマ生成では、ページ全体のコマ割りタグをそのまま入れない。
- ページ生成・精密ページ生成では、コマ境界、読み順、段、大小が追えるようにする。

参照:

- Manga Tag 品質ゲート: `.rulesync/skills/manga-tag-quality-gate/SKILL.md`
- 操作説明: `docs/image-generation/index.md`

## チャットモード

定義:
チャットモードは、作品契約（Phase 0）→ あらすじ（Phase 1）→ 執筆前パック（Phase 2）→ シーンカード（Phase 3）→ セグメント執筆（Phase 4）という段階をゲートで刻みながら進める対話型執筆方式である。Phase 0 完了後に3つのサブモードから進め方を選べる。

サブモード:

| モード | 意味 | Phase 1 の扱い |
|--------|------|----------------|
| **Script**（既定） | あらすじ先行・シーンカード合意後に執筆 | 先に完成 |
| **Freeform** | 作品契約のみを北極星に即興進行 | スキップ / 事後記録 |
| **NPC会話** | 特定キャラクターとして対話し、セッションログから小説化 | 任意 |

必須:

- 正本の所在は変わらない。本文は `novels/<作品>/_novel_text/novel_text*.md`、設定は同フォルダ内の各ファイルとする。
- `_chat/` フォルダ（副本）はセッションログ・シーンカード・ルールブック・state の一時置き場であり、完了扱いは正本への反映後とする。
- セグメント完了の定義は「完了扱い条件」と同一（正本への書き込み・確認・パス明示）。
- 物語の変化点、攻略・ゲーム性のある場面、合意ゲートでは、現在の Phase に応じた行動選択肢を最低2つと、システム操作・状態確認・Other などの非物語的な選択肢を最低1つ提示する。
- チャットやセッションで確定した物語の流れ・選択結果・攻略フラグは、逐語ログではなく要約として `design_specification.md` に適宜同期する。
- TRPG モードを使う場合、`_chat/rulebook.md` の生成後にユーザーの承認を得てから `_chat/state/*.md` の初期化へ進む。
- **セッション開始時**は `_chat/rulebook.md`・`_chat/state/char_state.md`・`_chat/state/world_state.md`・直近セッションログを必ず読み込んでから進める。
- **セッション終了時**は `[STATE UPDATE]` の差分を `_chat/state/*.md` に書き戻し、`sessions/chat_XX_YY.md` を保存してから終了する。

参照:

- スキル手順: `.rulesync/skills/novel-chat-mode/SKILL.md`（セッション継続プロトコル・Freeform・NPC会話を含む）
- パラメータテンプレート: `_how_to.example/trpg_rulebook.md`
- 操作説明: `docs/workflow/chat-writing-mode.md`

## TRPGパラメータ体系

定義:
チャットモードの TRPG セッションで使うパラメータは、個人能力・成長段階・関係性・物語状態の4カテゴリに分類し、尺度と更新条件を `_chat/rulebook.md` に定義してから運用する。

必須:

- パラメータは4カテゴリのどれかに分類し、カテゴリあたり2〜3個に絞る。
- セッション中のパラメータ変化は `[STATE UPDATE]` ブロックで「旧値 → 新値」の形で示す。
- セッション終了時に `_chat/state/*.md` へ現在値を書き戻す。
- `rulebook.md` の生成はジャンル別プリセットを出発点とし、ユーザー承認後に確定する。

参照:

- スキル手順: `.rulesync/skills/novel-chat-mode/SKILL.md`
- テンプレート: `_how_to.example/trpg_rulebook.md`

## rulesync

定義:
`rulesync` は、`.rulesync/` 配下の正本を LLM 別入口へ配布する生成・同期レイヤーである。

必須:

- ルールやスキルの主編集先は `.rulesync/` とする。
- `AGENTS.md` / `CLAUDE.md` などの入口ファイルは、原則として生成物・派生先として扱う。
- 入口ファイルへ内容を増やしたい場合は、先に `.rulesync/` 側の正本を更新する。
- `.rulesync/` 更新後、必要に応じて `rulesync generate` を実行し、入口ファイル差分を確認する。

参照:

- ルール作成規約: `.rulesync/rules/rule-authoring.md`
- 導入手順: `readme.md`, `docs/getting-started/index.md`
