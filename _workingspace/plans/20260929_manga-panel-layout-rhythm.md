# 漫画コマ割りのメリハリ改善（1ページ1〜5コマ・型の固定化解消）

- 作成日: 2026-09-29
- ブランチ: `feature/structure_2_1`
- 状態: 計画（未着手）。2026-09-29 に未決事項を決定済み（§8）

## 1. 背景と目的

漫画ページ IR（`manga/pages/manga_XX_pYY.yaml`）を起こすと、ほぼ毎ページが「4コマ・上1／中2／下1」または均等な縦4段に収束し、章全体でコマ数とコマの大小に起伏が出ない。

本計画のゴールは次の3つ。

1. **1ページ1〜5コマ**の範囲で、章内のコマ数に意図した分布が出る。
2. 見せ場・めくり・溜めがコマの**面積**として表れる（重要なコマほど大きい）。
3. 上記を LLM の気分ではなく、**工程・データ・検査**で担保する。

## 2. 原因（調査結果の要約）

| # | 原因 | 根拠 |
|---|------|------|
| A | 小説本文から直接ページ YAML を書いており、「拍子分解→ページ割り→コマ数決定」の工程が無い | `_how_to.example/manga.md` の手順は `_meta` の variant 表 → `manga/pages/*.yaml` |
| A' | 創作技法の正本 `manga.md` にコマ割りの節が無い。品質ゲートが参照する節は docs へ移設済みで参照切れ | `.rulesync/skills/manga-tag-quality-gate/SKILL.md` の §9 |
| B | 例が4コマに偏り、均等割りを合格扱いにしている | `tools/manga_prompt_ir/examples/manga_page.yaml`（上1中2下1）、`p4_compare/manga_01_p01.yaml`（同）、`docs/image-generation/manga-tag-generation.md:62`「縦に四分割」、`manga_tag_step2.md` §7「均等Nコマの一行でよい」 |
| C | レイアウトが自由記述の文字列だけで、コマの重み・大きさ・型IDが無い。`layout_geometry` は任意かつ手書き | `schemas/manga_page.py` の `MangaStyle.panel_layout: str`、`Composition.layout: str`、`Panel` に重みの欄が無い |
| D | 検査が `panel_layout` の空欄しか見ない。コマ数の範囲・章内分布・型の連続・大ゴマの有無を見ていない | `tools/novel_prompt_ir_validate.py:262-293` |
| E | ページ一括生成で「Nコマ」とだけ渡すと、画像モデルは均等グリッドを描きがち。座標があれば制約になるが、ほぼ未記入 | `image_provider_novel_manga_batch.py:1718-1721`、`page_render_plan.py` の Layout Geometry ブロック |

## 3. 方針

- **正本は引き続きページ YAML**。その上流に「章単位のページ割り計画」を足し、下流で座標を自動生成する。
- 追加する欄はすべて **schema 1.1 の任意欄**とし、`layout_geometry` と同じく 1.1 でのみ使える。既存の 1.0 ページは無改修で検証を通す（後方互換）。
- 1.0 ページで新しい欄を使うときは、**標準の移行手順**（`tools/novel_manga_ir_migrate.py` の dry-run で計画を作り、ハッシュ確認つきで apply）で 1.1 に上げてから付ける。移行手順はローカル側で改修中のため、統合後の手順に合わせて本計画の該当箇所を更新する。
- 型（テンプレート）は**データファイル**として持ち、コードに埋め込まない（`camera_shot_vocab.yaml` と同じ扱い）。
- 選択の偏りを避ける乱数選択は、既存の `weighted-pick`（`tools/json_weighted_pick.py`）の考え方を再利用する。
- 章単位の警告は、まず **WARNING**（`--strict-quality` で失敗扱い）から始め、通常エラーにはしない。
- 目標分布は**目安**であり、厳密に合わせにいかない。検査は「明らかに偏っている」ときだけ知らせる緩い閾値にする。

## 4. フェーズ別タスク

### フェーズ1: 例とドキュメントの是正（低リスク・即効）

- [ ] `_how_to.example/manga.md` に「コマ割り・ページ割り」節を新設する
  - 1ページ1〜5コマを基本とする。6コマ以上は作品ごとの設定で許可した場合のみ使う
  - 拍子の種類（導入・会話・反応・動作・見せ・山場・転換）と、コマ数・大小の目安
  - めくり（見せたい絵は次ページの頭、引きはページの左下）
  - 均等割りは「意図した場合のみ」。意図は `render_instruction.user_directives.page_notes` に1行残す
- [ ] `manga-tag-quality-gate/SKILL.md` §8・§9 の参照先を上記の新節へ直す。「均等Nコマの一行でよい」を「意図した均等割りのときのみ」に改める
- [ ] `_how_to.example/manga_tag_step2.md` §7 の同じ記述を改める
- [ ] `docs/image-generation/manga-tag-generation.md` の例を並べ替える（「縦に四分割」を先頭から外し、2・3・5コマの非均等例を先に置く）
- [ ] 例の分散: `tools/manga_prompt_ir/examples/manga_page.yaml` を3コマ（上段見せゴマ＋下段2コマ等）に変更し、5コマ例を1件追加する
  - `p4_compare/*` はテスト（`test_p4_compare_pages.py`）の固定データなので変更しない。変える場合はテストと同時に更新する
- [ ] `.rulesync/` を変更した場合は `uv run python tools/rulesync.py generate --dry-run` → `generate` で各エージェント向け出力を更新する

**完了条件**: `manga.md` だけを読んで、1〜5コマの使い分けと大ゴマを置く判断ができる。例のコマ数が 3／4／5／2 に分散している。

### フェーズ2: スキーマ拡張（schema 1.1 の任意欄として追加）

- [ ] `Panel` に追加
  - `weight: int | None`（1〜5。5＝そのページで最も見せたいコマ）
  - `size_class: Literal["splash", "large", "medium", "small", "inset"] | None`
  - `beat_type: str | None`（語彙は下記 `beat_type_vocab.yaml` で検査）
- [ ] `MangaStyle` に `layout_template_id: str | None` を追加
- [ ] 上記を `keep_schema_1_0_closed` の `versioned_keys` に登録し、schema 1.0 では使えない扱いにする（`layout_geometry` と同じ）
- [ ] `layout_template_id` があるときは、`layout_geometry` の枠数とコマ数が一致することを検証する
- [ ] テスト: `tools/manga_prompt_ir/tests/test_schema_validation.py` に、新しい欄の受理・1.0 での拒否・範囲外の値の拒否を追加する
- [ ] `docs/image-generation/manga-prompt-ir.md` のフィールド表を更新する

- [ ] 1.0 ページを 1.1 に上げる流れを `manga.md` と `docs/image-generation/manga-prompt-ir.md` に明記する（`novel_manga_ir_migrate.py` の dry-run → apply。ローカルで改修中の移行手順が統合されたら、その手順に差し替える）
- [ ] 移行ツールが新しい欄を落とさない・勝手に足さないことをテストで確認する（`test_manga_ir_migrate.py`）

**決定**: 新しい欄は schema 1.1 の任意欄として追加する（1.2 は切らない）。

### フェーズ3: 型ライブラリと自動配置

- [ ] `tools/manga_prompt_ir/data/panel_layout_templates.yaml` を新設する
  - コマ数 1〜5 ごとに 3〜5 型（計 15〜25 型程度）
  - 1型の中身: `template_id`、`panel_count`、`slots[]`（正規化矩形 x/y/w/h、`size_class`、読み順は右から左）、`suits`（会話・動作・山場・導入 などの用途タグ）、`gutter`、`bleed` 可否
  - 座標は余白込みで重ならないこと（既存の `GeometryRect` と重複検査をそのまま通す）
- [ ] `tools/manga_prompt_ir/data/beat_type_vocab.yaml` を新設する（拍子の種類と、既定の `weight`・推奨 `size_class` の対応）
- [ ] `tools/manga_prompt_ir/layout_templates.py` を新設する
  - 型の読み込みと自己検証（枠の重なり、ページ外、枠数とコマ数の一致）
  - 型の選択: コマ数・`beat_type` の構成・直前2ページの型を入力にし、直前と同じ型を除いたうえで重み付きで選ぶ
  - 配置: `weight` の大きいコマから面積の大きい枠へ割り当て、読み順の制約（`panel_id` 順）を守る範囲で入れ替える
  - 出力: `layout_geometry.panels[]` と `layout_template_id`
- [ ] CLI `tools/novel_manga_layout_apply.py` を新設する（`novel_manga_apply_tag_defaults.py` と同じく、既定は差分表示、`--apply` で書き込み）
  - 既に手書きの `layout_geometry` があるページは、`--overwrite` を付けない限り触らない
- [ ] テスト: 全型の自己検証、決定的な選択（シード固定）、重み順の割り当て、読み順の保持
- [ ] 生成側の確認: 座標が入ったページで、`page_render_plan.py` の Layout Geometry ブロック・`name_renderer.py`・`bubble_geometry.py` が動くこと（既存テストが通れば可）

**完了条件**: `weight` を付けたページに CLI を当てると `layout_geometry` が埋まり、ネーム画像で大小が目視できる。

### フェーズ4: 章単位の検査

- [ ] `tools/novel_manga_layout_lint.py` を新設する（最初は独立ツールとし、安定したら `novel_prompt_ir_validate.py` から呼ぶ）
  - 1ページのコマ数が 1〜5 の範囲外 → WARNING（作品設定 `manga_layout.allow_over_five_panels: true` のときは6コマ以上を許可し、上限 `max_panels_per_page` を超えたときだけ WARNING）
  - 章内で同じコマ数が 70% を超える → WARNING（目安の分布からのずれそのものは警告しない）
  - 同じコマ数または同じ `layout_template_id` が4ページ連続 → WARNING
  - 連続 N ページ（既定8）に、1〜2コマのページも面積40%以上の枠も無い → WARNING
  - `weight` の順位と枠面積の順位が逆転している → WARNING
  - 出力: 章ごとのコマ数ヒストグラムと、警告の一覧
- [ ] 作品設定は `_meta.yaml` の `manga_layout` 節に置く（案）

```yaml
manga_layout:
  allow_over_five_panels: false   # true で6コマ以上を許可
  max_panels_per_page: 5          # 許可時の上限（例: 8）
  target_distribution: {1: 0.05, 2: 0.15, 3: 0.30, 4: 0.30, 5: 0.20}
```

- [ ] 閾値の既定値はツール側に持ち、`_meta.yaml` で上書きできるようにする
- [ ] テスト: 全ページ4コマの章で警告が出る。分散した章で警告が出ない
- [ ] `manga-tag-quality-gate` に章単位の点検項目として追記する

### フェーズ5: ページ割り工程（上流）

- [ ] 章単位の計画ファイル `manga/plan/manga_XX_plan.yaml`（置き場所は決定済み）の形を決め、スキーマを作る（`tools/manga_prompt_ir/schemas/manga_plan.py`）
  - `target_distribution`（コマ数ごとの割合）
  - `beats[]`（`id`、本文の該当箇所、`beat_type`、`weight`）
  - `pages[]`（担当する拍子、`layout_template_id`、`page_turn_hook`）
- [ ] 目標分布の既定値を1種用意する（§8 の値）。ジャンル別プリセットは必要になってから足す。作品ごとの上書きは `_meta.yaml` の `manga_layout.target_distribution`
- [ ] 計画ファイルからページ YAML の骨組み（`panels[]` の数と `weight`・`beat_type`、`layout_template_id`）を起こす CLI を用意する
- [ ] `manga.md` の手順に「variant 表 → **ページ割り計画** → ページ YAML」の順を明記し、`manga-prompt-ir/SKILL.md` の「Manga Tag の入口」を更新する
- [ ] `workflow-specification.md` の成果物一覧に `manga/plan/` を追加する

**完了条件**: 新しい章を計画ファイルから起こしたとき、フェーズ4の検査で警告が出ない。

## 5. 参照データの扱い

- Manga109 のコマ矩形の注釈は、1ページのコマ数・面積比の分布を**較正する数値**としてのみ参照する。学術利用限定のため、型の座標を写したり、データをリポジトリに含めたりしない。
- 型の座標は自前で設計する。必要ならギロチン分割（縦横の再帰分割）で候補を機械生成し、人が選別して YAML に固定する。
- 斜めのコマ枠は今回の対象外（`GeometryRect` は軸に平行な矩形のみ）。必要になった時点で shapely の導入を検討する。

## 6. リスクと対策

| リスク | 対策 |
|--------|------|
| 自動配置が本文の意図と合わない | CLI は既定で差分表示のみ。手書きの座標は上書きしない |
| 検査の警告が多すぎて無視される | WARNING から開始し、実作品1章で閾値を調整してから品質ゲートに載せる |
| 画像モデルが座標どおりに描かない | 当面は `step1-panels`（コマ単位生成）＋合成を主経路にし、座標はネーム・写植・合成に使う。一括生成での再現度は別途計測する |
| 例の変更で既存テストが壊れる | `p4_compare` は触らない。`manga_page.yaml` を使うテストを先に洗い出す |

## 7. 着手順と見積もり（目安）

1. フェーズ1（ドキュメント・例）— 小
2. フェーズ2（スキーマ）— 小
3. フェーズ3（型ライブラリ・自動配置）— 中〜大（型の設計が本体）
4. フェーズ4（章単位の検査）— 中
5. フェーズ5（ページ割り工程）— 中

フェーズ1だけでも LLM の出力の偏りは下がる見込み。2〜4 で機械的な担保、5 で上流から設計できる状態にする。

## 8. 決定事項（2026-09-29）

- [x] 新しい欄は **schema 1.1 の任意欄**として追加する。1.0 ページは標準の移行手順（`novel_manga_ir_migrate.py`）で 1.1 に上げてから使う。移行手順はローカル側で改修中で、統合後に本計画の記述を合わせる
- [x] 目標分布の既定値は 1コマ 5%／2コマ 15%／3コマ 30%／4コマ 30%／5コマ 20%。**目安として扱い、無理に合わせない**（検査の閾値も緩くする）
- [x] 6コマ以上のページは**作品ごとの設定で許可**する（`_meta.yaml` の `manga_layout.allow_over_five_panels`）
- [x] 章ごとの計画ファイルは **`manga/plan/`** に置く

## 8.1 残る確認事項

- [ ] ローカルで改修中の移行手順が統合されたら、フェーズ2の移行の記述とテストを合わせる

## 9. 検証コマンド（各フェーズ共通）

```bash
uv run pytest tools/manga_prompt_ir/tests
uv run python tools/novel_prompt_ir_validate.py novels/<作品> --strict-quality
uv run python tools/rulesync.py generate --dry-run   # .rulesync を変更したとき
```

実施した作業は `_workingspace/log/YYYYMM.md` に査証ログとして残す。
