# Monogatari Creator Meta Information System

このファイルは、小説の「外部向けメタ情報（投稿用）」と「内部向けメタ情報（執筆管理・AI指示用）」の両方を定義します。

---

# I. 内部メタ情報（Internal Meta: 執筆管理・AI指示用）
執筆を中断・再開する際や、次の章へ進む際に、AIが文脈を完璧に把握するための「引き継ぎ用メタ情報」です。

## 1. 執筆フェーズ・ステータス
- **現在のフェーズ**: (企画/設計/プロット/執筆/校正/完結)
- **現在の章・項**: (例: 第3章 第2項)
- **進捗率**: (全体の何%程度か)
- **次回のタスク**: (次にAIが何をすべきか、具体的な指示)

## 2. 執筆用コンテキスト・アンカー
- **直近の重要イベント**: (前の章で何が起きたか、何が確定したか)
- **保持すべき「熱量/トーン」**: (例: ここからは絶望感を強める、コメディ調を維持する)
- **伏線・フラグ管理**: (現在生きている伏線、この章で回収すべきフラグ)
- **読者への約束（フック）**: (このセクションで読者に何を見せる予定か)

## 3. 執筆制約・メタ指示
- **絶対に避ける描写**: (例: 主人公の弱体化、特定キャラの死亡など)
- **優先すべき語彙・レトリック**: (特定の作家の癖や、よく使う比喩)
- **AIへの「なりきり」指示**: (例: 「今は編集者として厳しく見て」「今は情熱的な作家として一気に書いて」)

---

# II. 外部メタ情報（External Meta: カクヨム等投稿サイト・投稿用）
読者やプラットフォームに向けた、作品の「顔」となる情報です。

## 1. カクヨム基本項目
- **キャッチコピー**: (25〜45字)
- **紹介文（短・中・長）**:
- **タグ**: (王道タグ ＋ 独自タグ)
- **セルフレイティング**: (暴力/残酷/性的/その他)

## 2. ターゲット・訴求
- **想定読者層**:
- **読後感の期待値**:
- **作品の3つの魅力**:

---

# III. 画像・漫画生成設定（Image / Manga Generation）
漫画タグ（Manga Tag Mode）・画像生成の既定設定を記録します。エージェントはセッション開始時にここを参照し、`--color-mode` 等のフラグを決定します。

## 0. 機械可読メタ（`_meta.yaml`・定量）

散文・進捗・§4/§5 の表は **`_meta.md`** のまま。**バッチが読む数値・パス**は作品フォルダ直下の **`_meta.yaml`** に書く（雛形: **`_how_to.example/_meta.yaml.example`**）。

新規作品では Plan 完了時に次を実行する:

```bash
python tools/novel_scaffold.py novels/NNN_作品名
```

| 項目 | 正本 | 備考 |
|------|------|------|
| 執筆進捗・伏線・投稿文 | `_meta.md` | LLM 向け散文 |
| NovelAI ポーション（path / strength） | `_meta.yaml` → `novelai.portions` | `image_provider_novel_manga_batch.py` が自動読込 |
| コマのタグ・variant | `manga/pages/*.yaml` | 実行の最終正本 |

**優先順位（ポーション）**: CLI `--novelai-reference-image-path` ＞ `_meta.yaml` ＞ `.env` ＞ なし。

```yaml
# _meta.yaml（抜粋）
version: 1
novelai:
  portion_default: cross_flat
  portion_fallback: cross_flat
  portions:
    cross_flat:
      path: _how_to/image_refs/novelai/2026-05-17_flat.naiv4vibebundle
      strength: 0.6
      information_extracted: 1.0
```

別ポーションを試すとき: `--novelai-portion-id work_manga`。詳細は **`_how_to.example/image_refs/novelai/README.md`**。

## 1. 色モード
- **作品基準**: （`full_color` / `monochrome` / `limited_color` のいずれかを記載）
- **備考**: （センターカラー・巻頭カラーなど意図的に別モードを使うページがあれば記載）

## 2. 生成 provider 既定（任意）
- **コマ生成 (step1-panels)**: （例: novelai）
- **ページ生成 (step1-pages / step2-pages)**: （例: grok_pro）
- **背景資料 (background-concepts)**: （例: grok）

## 3. 挿絵・表紙（任意・作品ごと）

挿絵の**密度・優先場面・表紙の有無**は、本文 IR ではなくここに書いておくと、執筆・画像タスクのブレを防げる。**表紙は原則として計画に含める**（電子書籍のみ／印刷想定あり 等も一言）。

- **挿絵の方針**: （例: 章頭に0〜1枚 / N万字ごとに高々1枚 / クライマックスのみ）
- **優先する場面**: （箇条書き。例: 主人公とライバルの初対面、世界観のReveal）
- **挿絵にしない条件**: （例: ネタバレ箇所、回想のみの章）
- **表紙**: （作る／後回し／外注）。作る場合のメモ（単行本・カクヨム表紙サイズ、ロゴ・タイトル安全圏）
- **IR の番号設計（メモ）**: （例: `illustration_00`＝表紙、`illustration_01`〜＝章挿絵。実体は `novels/<作品>/illustrations/pages/` の YAML 正本）

## 4. 漫画 variant 対応（TPO 正本・YAML より先に更新）

Manga Tag では **`manga/pages/*.yaml` より先に**、本文区間ごとの **状況バリアント（`01_` 以降）** をここで固定し、チャットで合意してから YAML に落とす。書き方・`00_base` の扱いは **`_how_to.example/manga.md`** の「TPO → variant 対応表」を正とする。

| 区間（ページ／本文） | 本文参照 | （キャラID）variant | … | メモ |
|----------------------|----------|---------------------|---|------|
| （例: manga_01_p01–p04） | novel_text01 … | yuma: `06_nude` | … | 連続場面 |

**variant 表に「常時タグ」を混ぜない。** 衣装・裸露・固定外見はキャラの `variant_id` と `tag/characters/*.yaml` の責務。区間で全コマに足す**場・光・画風・禁止トークン**は **§5 タグ層** に書く。

## 5. 漫画タグ層（区間・常時上乗せ・YAML より先に更新）

**ページのあいだ（例: `manga_01_p01`〜`p04`）で、全コマに同じ属性タグを足したい／外したい**とき用。variant 対応（§4）と**別表**にする。

| 役割 | 何を書くか | 正本（合意） | 実行（バッチが読む） |
|------|------------|--------------|----------------------|
| キャラの身体・衣装 | `variant_id` | §4 の表 | `panels[].subjects[].variant_id` |
| **区間の常時タグ** | 英語トークン列 | **§5 の表（本節）** | 区間内の**各ページ YAML** の `render_instruction.user_directives.defaults` |
| コマ固有 | 姿勢・画角・接触など | チャット／`summary` | `panels[].prompt_tags` |

**ツールは `_meta.md` の §5 を自動読み込みしない。** 合意した内容を、区間に含まれる **ページごとに同じ `defaults` ブロック**として YAML に写す（写し忘れ防止のため、§5 の表に「YAML 反映済」列を足してもよい）。

### 表の書き方（最小）

```markdown
### 漫画タグ層（区間・常時上乗せ）

| 区間 | 本文参照 | required（全コマに足す） | omit（全コマから外す） | メモ |
|------|----------|--------------------------|-------------------------|------|
| manga_01_p01–p04 | novel_text01 浴室 | steam, bathroom, warm_amber_lighting | outdoor, sky, classroom | §4 浴室 variant と併用 |
```

- **区間**の表記は §4 と同じ（`manga_01_p01–p04`、項名、本文章など）。
- **required / omit** は `manga_tag.md` の語彙に合わせた **英語トークン**（カンマ区切りを表のセルに書いてよい）。
- **コマだけ例外**にしたいときは、§5 ではなく該当 `panels[].required_prompt_tags` / `omit_prompt_tags` に書く。

### YAML への反映（区間 → 各ページ）

区間 `manga_01_p01`〜`p04` なら、**4ファイルすべて**に同型の `defaults` を入れる。

```yaml
render_instruction:
  user_directives:
    page_notes:
      - "_meta §5: manga_01_p01–p04 浴室タグ層"
    defaults:
      required_prompt_tags:
        - steam
        - bathroom
        - warm_amber_lighting
      omit_prompt_tags:
        - outdoor
        - sky
```

- 合成順・検証は **`render_instruction.user_directives`**（`tools/manga_prompt_ir/user_directives.py`）。`step1-panels` / 互換 Step1 エクスポートの両方に効く。
- **ページをまたぐ同一舞台**では、`scene` / `background_notes_en` / `manga.genre_tags` も揃える。§5 は **`prompt_tags` への強制加算・除外**が目的（§4 variant とは独立）。
- **背景資料と合成する**運用では、コマから浴室タグを外したい区間は §5 の required を見直すか、`--omit-panel-background` を検討（`docs/image-generation/index.md`）。

### 推奨のやりとり順（§4 とセット）

1. §4 で **variant** を区間ごとに合意する。
2. §5 で **常時タグ** を区間ごとに合意する（「この間はずっと湯気」「屋外タグは禁止」など）。
3. `manga/pages/*.yaml` を書く（`variant_id` は §4、`defaults` は §5 をページ単位に複写）。
4. `embed_snapshots` → `novel_prompt_ir_validate.py` → エクスポート／生成。

詳細なフィールド定義は **`.rulesync/skills/manga-prompt-ir/SKILL.md`** の「ユーザ指示の正本」を参照。

---

# IV. メタ情報生成・更新プロンプト（AIへの指示）

### 執筆終了時（引き継ぎ用）
「今回の執筆内容を元に、`meta.md` の『内部メタ情報』を更新してください。特に『直近の重要イベント』と『次回のタスク』を具体的に記載し、次回のセッションで私が文脈を失わないようにしてください。」

### 執筆開始時（文脈復旧用）
「`meta.md` の『内部メタ情報』と `config.md` を読み込み、現在の執筆ステータスと『次回のタスク』を確認してください。その上で、今日取り組む内容の作業計画を提示してください。」

### 完結時（投稿準備用）
「作品の全容を把握した上で、`meta.md` の『外部メタ情報』セクションを埋めてください。カクヨムで目を引くキャッチコピーと、読者が読みたくなる紹介文を3案ずつ提案してください。」
