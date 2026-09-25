# IR互換漫画ページ

<!-- manga-prompt-ir互換ヘッダ: このmanga_XX.mdは既存バッチ向けMarkdown互換出力です。構造化IR正本は manga/pages/*.yaml を参照してください。 -->

## IR正本

- `tools/manga_prompt_ir/examples/p4_compare/manga/pages/manga_01_p01.yaml`

## Page 1

### Step1
カラー漫画、日本の漫画のコマ割り、1ページ4コマ、読み順: right_to_left
ページ構成: 上1・中2・下1
共通舞台: station waiting room / late afternoon / 

### Schema 1.1 context
Structured schema 1.1 context:
Lettering Style:
- baseline_direction=vertical; base_font_size=30; size_policy=uniform_then_shrink (post-processing)
Page Purpose and Dramaturgy:
- purpose: Two friends choose a destination from a ticket.
Panel Dramaturgy and Background Density:
- panel 10: role=establish; purpose=Show place, both people, and the ticket.; background_density=medium
- panel 20: role=reverse; purpose=Make Kazuki's line clear.; background_density=sparse
- panel 30: role=information; purpose=Show the printed ticket face large.; background_density=sparse
- panel 40: role=decision; purpose=They agree and stand.; background_density=medium
Character Slots:
- slot_id=p10-s01; panel_id=10; subject_id=p10-s01; character_id=kazuki; variant_id=001_normal; action=looking at the ticket; expression=hesitant; position=midground
- slot_id=p10-s02; panel_id=10; subject_id=p10-s02; character_id=yui; variant_id=001_normal; action=holding out a paper ticket; expression=smile; position=midground
- slot_id=p10-s03; panel_id=10; subject_id=p10-s03; action=in her right hand; position=foreground
- slot_id=p20-s01; panel_id=20; subject_id=p20-s01; character_id=kazuki; variant_id=001_normal; action=slight frown; expression=questioning; position=foreground
- slot_id=p30-s01; panel_id=30; subject_id=p30-s01; character_id=yui; variant_id=001_normal; action=turning the ticket to camera; expression=smile; position=midground
- slot_id=p30-s02; panel_id=30; subject_id=p30-s02; action=held in fingers; position=foreground
- slot_id=p40-s01; panel_id=40; subject_id=p40-s01; character_id=kazuki; variant_id=001_normal; action=looking toward the platform; expression=resolved; position=midground
- slot_id=p40-s02; panel_id=40; subject_id=p40-s02; character_id=yui; variant_id=001_normal; action=standing with the ticket; expression=satisfied; position=midground
Continuity Tracks:
- entity_id=ticket; panel_id=10; state=in Yui's right hand
- entity_id=ticket; panel_id=30; state=printed face close-up
Layout Geometry:
- panel 10: rect=(0.04, 0.03, 0.92, 0.28)
- panel 20: rect=(0.52, 0.34, 0.44, 0.3)
- panel 30: rect=(0.04, 0.34, 0.44, 0.3)
- panel 40: rect=(0.04, 0.67, 0.92, 0.3)
Asset References (ordered attachments when a path is supplied):
- asset_id=paper-ticket; role=prop; attachment=not_requested

**コマ10: ベンチで2人。結が切符を出す。**
- 人物・対象: 和紀（Kazuki）、座る和紀、切符を見る、戸惑い、midground / 結（Yui）、切符を持つ結、切符を差し出す、笑顔、midground / 紙の切符、紙の切符、右手に持つ、foreground
- 構図: 上段 / medium shot / 切符 / 
- セリフ: yui「これ、見て。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, station_waiting_room, late_afternoon, seated, paper_ticket, holding_ticket, looking_at_ticket, two_shot, two-shot, medium_shot, two_faces, paper_train_ticket, in_her_right_hand, foreground | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, looking_at_the_ticket, hesitant, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, holding_out_a_paper_ticket, smile, midground`
（日本語訳：ベンチで2人。結が切符を出す。）

**コマ20: 和紀が切符を見て聞き返す。**
- 人物・対象: 和紀（Kazuki）、和紀の顔、眉を寄せる、疑問、foreground
- 構図: 中段右 / close-up / 口元 / 
- セリフ: kazuki「駅の切符？」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, station_waiting_room, late_afternoon, questioning_expression, slight_frown, mouth_focus, close-up, bust, mouth, solo_bust | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, slight_frown, questioning, foreground`
（日本語訳：和紀が切符を見て聞き返す。）

**コマ30: 結が切符の印刷面を見せる。**
- 人物・対象: 結（Yui）、切符を掲げる結、印刷面を向ける、笑顔、midground / 切符の印刷面、切符の印刷面、指で支える、foreground
- 構図: 中段左 / close-up / 印字面 / 
- セリフ: yui「今日の行き先。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, station_waiting_room, late_afternoon, paper_ticket, printed_ticket, holding_ticket, close-up, ticket_close-up, printed_face, inspect_close-up, printed_ticket_face, held_in_fingers, foreground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, turning_the_ticket_to_camera, smile, midground`
（日本語訳：結が切符の印刷面を見せる。）

**コマ40: 2人が立ち上がる。**
- 人物・対象: 和紀（Kazuki）、立つ和紀、ホーム側を見る、決意、midground / 結（Yui）、立つ結、切符を持って立つ、満足、midground
- 構図: 下段 / medium shot / 2人と切符 / 
- セリフ: kazuki「……行こう。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, station_waiting_room, late_afternoon, standing, looking_toward_exit, two_shot, resolved_expression, two-shot, both_figures_and_ticket, medium_shot, two_faces | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, looking_toward_the_platform, resolved, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, standing_with_the_ticket, satisfied, midground`
（日本語訳：2人が立ち上がる。）

### Step2
カラー漫画、日本の漫画のコマ割り、1ページ4コマ。上1・中2・下1。numbered panels、読み順は right_to_left。
- コマ10: 上段。ベンチで2人。結が切符を出す。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
- コマ20: 中段右。和紀が切符を見て聞き返す。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants
- コマ30: 中段左。結が切符の印刷面を見せる。 【固定見た目】結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
- コマ40: 下段。2人が立ち上がる。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
