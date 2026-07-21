# Publishing Package（Phase 1）

本文・挿絵・権利・奥付の**入稿用入力一式**を、各作品フォルダの中で宣言・点検・凍結するための運用です。Phase 1 は PDF / EPUB を組版する機能ではありません。組版へ渡す入力の欠落や参照ずれを、再現できる形で検出します。

## 置き場所と正本

出版パッケージのルートは `novels/<作品>/` です。本文や画像を別の `manuscript/` / `assets/` へ複写しません。

```text
novels/<作品>/
├─ book.yaml                         # 書誌・原稿順・挿絵・奥付・出力の宣言
├─ rights.yaml                       # 素材・フォントの許諾記録
├─ book.lock.yaml                    # lock コマンドが生成（手編集しない）
├─ character.md                      # 制作・設定用の人物資料
├─ _novel_text/                      # 物語本文の正本
├─ book_matter/
│  ├─ frontmatter/characters.md      # 読者向けの「登場人物」
│  └─ backmatter/                    # あとがき・読後向け解説（必要な場合）
└─ illustrations/                    # 挿絵 IR と採用画像
```

`character.md` は執筆者のための詳細設定、`book_matter/frontmatter/characters.md` は読者が本文の前に読む付属原稿です。制作資料をそのまま複写せず、読前に必要な情報だけに書き分けます。

## 読者向け「登場人物」テンプレート

次を `book_matter/frontmatter/characters.md` の出発点にします。年齢や正体、関係の変化など、本文の驚きを失わせる情報は書きません。

```markdown
# 登場人物

## 水城 澪（みずき・みお）

夜明け前の港町で暮らす見習い航海士。静かな観察眼と、困っている人を放っておけない気質を持つ。

## アルド

澪の航海に同行する、口数の少ない護衛。古い地図を手放さない。

<!-- illustration: illust_character_mio -->
```

人物ごとに必要なのは、原則として**名前・呼び名・第一印象・物語の入口での役割**だけです。外見の細部、能力値、制作上の課題、裏設定は `character.md` に残します。

人物紹介の絵を置く場合、Markdown には画像パスを書かず `<!-- illustration: <id> -->` を一つだけ記します。`<id>` は `book.yaml` の `illustrations[].id` と一致させ、`type: character_intro`、`scene_ref: null` にします。

```yaml
manuscript:
  frontmatter:
    - id: characters
      title: "登場人物"
      file: book_matter/frontmatter/characters.md
      start_page_policy: odd_page

illustrations:
  - id: illust_character_mio
    type: character_intro
    color: true
    scene_ref: null
    brief: "港の朝靄の中に立つ澪の紹介用カット"
    status: planned
    asset: null
```

読了後の正体・関係・結末に触れる人物解説が必要な場合だけ、`book_matter/backmatter/characters_afterword.md` を `manuscript.backmatter` に追加します。通常の「登場人物」へネタバレ版を混在させません。

## 原稿と挿絵の参照規約

章の先頭・場面の切替点など、挿絵を置きたい本文位置に次のアンカーを記します。

```markdown
<!-- scene: ch01-003 -->

澪は桟橋の端で、海図を開いた。
```

章 ID は `book.yaml` の `manuscript.chapters[].id`（`ch01` 形式）に一致させます。同じ `ch01-003` は、分割した章ファイルを含めて一度だけにします。

本文中の挿絵位置は `<!-- illustration: illust_001 -->` で記します。実ファイルの場所は `book.yaml` の `illustrations[].asset` のみを正本にします。`type: insert` の挿絵は、必ず実在する `scene_ref` を持たせます。

宣言ファイル内のパスは作品フォルダ基準の `/` 区切りです。絶対パス、`..`、`./`、Windows の `\\` 区切りは使えません。

## 最小導入と確認

最小のスキーマ例は [`tools/fixtures/book_package/`](../../tools/fixtures/book_package/) にあります。作品に導入するときは `book.yaml` と `rights.yaml` を作成し、実際の章・付属原稿・挿絵 ID に合わせて書き換えます。

執筆中は、未定の奥付や表紙許諾を情報として出す writing ゲートを使います。

```bash
python tools/book_review.py novels/NNN_作品名 --gate writing
```

入稿前は export ゲートを対象別に通します。`error` が一件でもあれば終了コードは `1` で、lock は作れません。

```bash
python tools/book_review.py novels/NNN_作品名 --gate export --target paper
python tools/book_review.py novels/NNN_作品名 --gate export --target ebook
```

ebook では奥付に加え、表紙の `ebook: allowed` 許諾と `export.ebook.cover_image` の実在が必要です。詳細な結果を他ツールへ渡すときは `--json` を付けます。

## lock と変更検出

export review がエラーなしになった対象だけを lock します。`book.lock.yaml` は `book.yaml`、`rights.yaml`、本文・付属原稿、採用挿絵の SHA-256 を保存する生成物です。直接編集しません。

```bash
python tools/book_lock.py novels/NNN_作品名 --target paper
python tools/book_diff.py novels/NNN_作品名 --against lock
```

lock 後に原稿や採用画像を変えると `book_diff.py` が `added` / `removed` / `changed` を示し、次回 review に P-E02 の警告が出ます。差分を確認し、再度 export review を通してから lock を作り直します。

## 既存作品への移行順

1. `character.md` を正本のまま残し、ネタバレを除いた `characters.md` を新設する。
2. `book.yaml` の章一覧に既存 `_novel_text/novel_text*.md` を**複写せず**列挙する。章を項に分けている場合は順序付き `files` を使う。
3. 本文に `<!-- scene: chNN-XXX -->` を加え、既存挿絵計画の位置を `scene_ref` へ対応付ける。
4. 採用画像だけを `illustrations[].asset` に登録し、権利根拠を `rights.yaml` に記録する。
5. writing review で参照の不足を直し、入稿時に export review → lock → diff の順で確認する。

この導入は既存の本文・挿絵 IR・画像生成フローを変更しません。Phase 1 の対象外である PDF / EPUB 組版、表紙文字の合成、契約文の法的判断は、後続フェーズで扱います。
