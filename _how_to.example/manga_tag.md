# 取り扱い方
タグ生成の参考に使う。

## 構造化IR優先（manga-prompt-ir）

漫画タグは、まず `manga-prompt-ir` の `MangaPagePrompt.panels[].prompt_tags` として保持する。
`manga_XX.md` の `tag:` 行は、既存バッチ互換のための出力層であり、正本は `manga/pages/*.yaml` とする。

ただし、IR は生成途中で壊れたら作り直してよい中間データである。守るべきものは、タグ形式そのものではなく、次の日本語の意味である。

- 誰が写っているか
- 誰に向けた行為か
- どこで起きているか
- 何をしているか
- セリフ・モノローグ・ナレーション・効果音の帰属
- コマの段・大小・読み順・役割

登場キャラがいる場合は、`tag/characters/<character_id>.yaml` と `tag/<romaji>.md` を参照し、髪・目・肌・種族・体格・固定小物などの固定特徴を `prompt_tags` へ継承する。

# 基本的な指示出し
コマごとに場所 (Location),人の状態 (Characters' States),行っているアクション (Actions)などを明確にしてください
登場キャラがいる場合は、**`character.md` と `tag/<romaji>.md` を正として、髪・目・肌・種族・体格・固定小物などの固定特徴を各コマのタグへ継承してください**。
たとえば、
男性が水中で溺れる女性を救助し、抱きかかえている。
という状態を、場所、2人の状態、行っているアクション等を明記した状態でタグにしてください。

underwater scene, swimming pool interior, clear blue water, bubbles floating, dim underwater lighting,
1boy, muscular build, wet clothes, determined expression, short hair,
1girl, slender build, long hair flowing in water, panicked expression, eyes wide open, mouth open gasping for air, soaked dress clinging to body,
boy rescuing girl, boy carrying girl in arms, bridal carry pose, girl clinging to boy desperately, boy swimming upwards with girl,
dynamic action pose, water splashes, sense of urgency, dramatic shadows

# 背景
- 背景のみのシーンの場合はnohumanを入れる

# 効果音を入れる
コマのシーンに入れる場合
sound effects visualization
