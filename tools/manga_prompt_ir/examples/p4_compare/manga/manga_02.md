# IR互換漫画ページ

<!-- manga-prompt-ir互換ヘッダ: このmanga_XX.mdは既存バッチ向けMarkdown互換出力です。構造化IR正本は manga/pages/*.yaml を参照してください。 -->

## IR正本

- `tools/manga_prompt_ir/examples/p4_compare/manga/pages/manga_02_p01.yaml`

## Page 1

### Step1
カラー漫画、日本の漫画のコマ割り、1ページ3コマ、読み順: right_to_left
ページ構成: 上動作・中反応・下見せゴマ
共通舞台: station waiting room / late afternoon / 

### Schema 1.1 context
Structured schema 1.1 context:
Lettering Style:
- baseline_direction=vertical; base_font_size=30; size_policy=uniform_then_shrink (post-processing)
Page Purpose and Dramaturgy:
- purpose: Kazuki catches a falling ticket.
Panel Dramaturgy and Background Density:
- panel 10: role=action; purpose=One beat for the drop.; background_density=medium
- panel 20: role=Reaction; purpose=Face reaction only.; background_density=sparse
- panel 30: role=splash; purpose=Large catch panel.; background_density=medium
Character Slots:
- slot_id=p10-s01; panel_id=10; subject_id=p10-s01; character_id=yui; variant_id=001_normal; action=ticket leaving her right hand; expression=alarmed; position=midground
- slot_id=p10-s02; panel_id=10; subject_id=p10-s02; character_id=kazuki; variant_id=001_normal; action=reaching for the falling ticket; expression=focused; position=midground
- slot_id=p10-s03; panel_id=10; subject_id=p10-s03; action=falling; position=foreground
- slot_id=p20-s01; panel_id=20; subject_id=p20-s01; character_id=yui; variant_id=001_normal; action=hands raised, frozen; expression=startled; position=foreground
- slot_id=p30-s01; panel_id=30; subject_id=p30-s01; character_id=kazuki; variant_id=001_normal; action=catching the ticket near the floor; expression=relieved; position=foreground
- slot_id=p30-s02; panel_id=30; subject_id=p30-s02; character_id=yui; variant_id=001_normal; action=hand on chest, looking down; expression=relieved; position=midground
- slot_id=p30-s03; panel_id=30; subject_id=p30-s03; action=held between fingers; position=foreground
Continuity Tracks:
- entity_id=ticket; panel_id=10; state=falling from Yui's hand
- entity_id=kazuki; panel_id=30; state=catching the ticket
Layout Geometry:
- panel 10: rect=(0.04, 0.03, 0.92, 0.28)
- panel 20: rect=(0.04, 0.34, 0.92, 0.26)
- panel 30: rect=(0.04, 0.63, 0.92, 0.34)
Asset References (ordered attachments when a path is supplied):
- asset_id=paper-ticket; role=prop; attachment=not_requested

**コマ10: 切符が落ち、和紀が手を伸ばす。**
- 人物・対象: 結（Yui）、切符を落とす結、右手から切符が離れる、焦り、midground / 和紀（Kazuki）、手を伸ばす和紀、落ちる切符へ手を伸ばす、集中、midground / 空中の切符、空中の切符、落ちる、foreground
- 構図: 上段 / medium shot / 落ちる切符 / 
- 効果音: ぱらっ（切符が指を離れる）
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, speed_lines, clean_lineart, station_waiting_room, late_afternoon, falling_ticket, reaching, action_pose, focused_expression, action_shot, medium_shot, two_faces, paper_ticket_in_mid-air, falling, foreground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, ticket_leaving_her_right_hand, alarmed, midground | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, reaching_for_the_falling_ticket, focused, midground`
（日本語訳：切符が落ち、和紀が手を伸ばす。）

**コマ20: 結が目を見開く。**
- 人物・対象: 結（Yui）、驚く結、両手を上げて固まる、驚き、foreground
- 構図: 中段 / close-up / 結の目 / 
- セリフ: yui「あっ」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, speed_lines, clean_lineart, station_waiting_room, late_afternoon, wide_eyes, startled_expression, reaction_close-up, Yui's_eyes, close-up, solo_face | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, hands_raised,_frozen, startled, foreground`
（日本語訳：結が目を見開く。）

**コマ30: 和紀が切符をつかむ見せゴマ。**
- 人物・対象: 和紀（Kazuki）、切符をつかむ和紀、床近くで切符をつかむ、安堵、foreground / 結（Yui）、見下ろす結、胸に手を当てる、安堵、midground / つかんだ切符、つかんだ切符、指の間で止まる、foreground
- 構図: 下段 / wide shot / つかんだ切符 / 
- セリフ: kazuki「取った。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, speed_lines, clean_lineart, station_waiting_room, late_afternoon, catching, caught_ticket, near_floor, splash_panel, splash, long_shot, caught_paper_ticket, held_between_fingers, foreground | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, catching_the_ticket_near_the_floor, relieved, foreground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, hand_on_chest,_looking_down, relieved, midground`
（日本語訳：和紀が切符をつかむ見せゴマ。）

### Step2
カラー漫画、日本の漫画のコマ割り、1ページ3コマ。上動作・中反応・下見せゴマ。numbered panels、読み順は right_to_left。
- コマ10: 上段。切符が落ち、和紀が手を伸ばす。 【固定見た目】結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote ｜ 和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants
- コマ20: 中段。結が目を見開く。 【固定見た目】結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
- コマ30: 下段。和紀が切符をつかむ見せゴマ。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
