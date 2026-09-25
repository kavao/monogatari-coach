# IR互換漫画ページ

<!-- manga-prompt-ir互換ヘッダ: このmanga_XX.mdは既存バッチ向けMarkdown互換出力です。構造化IR正本は manga/pages/*.yaml を参照してください。 -->

## IR正本

- `tools/manga_prompt_ir/examples/p4_compare/manga/pages/manga_03_p01.yaml`
- `tools/manga_prompt_ir/examples/p4_compare/manga/pages/manga_03_p02.yaml`

## Page 1

### Step1
カラー漫画、日本の漫画のコマ割り、1ページ2コマ、読み順: right_to_left
ページ構成: 上段到着・下段着席の2段
共通舞台: small railway station waiting room / late afternoon / 

### Schema 1.1 context
Structured schema 1.1 context:
Lettering Style:
- baseline_direction=vertical; base_font_size=30; size_policy=uniform_then_shrink (post-processing)
Page Purpose and Dramaturgy:
- purpose: Both enter the same place and set up the next-page conversation.
- emotional arc: From arrival to sitting down.
Panel Dramaturgy and Background Density:
- panel 10: role=establish; purpose=Lock location and costumes for the following page.; background_density=dense
- panel 20: role=settle; purpose=Move into the seated state used on the next page.; relation_to_previous=After moving from the door to the bench.; background_density=medium
Character Slots:
- slot_id=p10-s01; panel_id=10; subject_id=p10-s01; character_id=kazuki; variant_id=001_normal; action=pausing just inside the doorway; expression=calm; position=midground
- slot_id=p10-s02; panel_id=10; subject_id=p10-s02; character_id=yui; variant_id=001_normal; action=walking a step ahead while holding the ticket; expression=guiding; position=midground
- slot_id=p20-s01; panel_id=20; subject_id=p20-s01; character_id=kazuki; variant_id=001_normal; action=sitting with both hands on his knees; expression=waiting; position=midground
- slot_id=p20-s02; panel_id=20; subject_id=p20-s02; character_id=yui; variant_id=001_normal; action=placing the ticket on her lap; expression=calm; position=midground
Continuity Tracks:
- entity_id=location; panel_id=10; state=entering the waiting room
- entity_id=yui; panel_id=20; state=sitting with ticket in hand
Layout Geometry:
- panel 10: rect=(0.04, 0.03, 0.92, 0.45)
- panel 20: rect=(0.04, 0.52, 0.92, 0.45)
Asset References (ordered attachments when a path is supplied):
- asset_id=kazuki-normal; role=character; character_id=kazuki; attachment=not_requested
- asset_id=yui-normal; role=character; character_id=yui; attachment=not_requested
- asset_id=station-room; role=location; concept_id=station_waiting_room; attachment=not_requested

**コマ10: 待合室の入口から2人が並んで入ってくる。**
- 人物・対象: 和紀（Kazuki）、入口に立つ和紀、ドア枠の内側で立ち止まる、落ち着き、midground / 結（Yui）、隣に立つ結、切符を持って和紀の少し前を歩く、案内する顔、midground
- 構図: 上段 / wide shot / 入口と2人の全身 / 
- セリフ: yui「ここ。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, small_railway_station_waiting_room, late_afternoon, clear_evening_light, doorway, entering, standing, two_shot, wide_arrival_shot, doorway_and_both_full_figures, long_shot | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, pausing_just_inside_the_doorway, calm, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, walking_a_step_ahead_while_holding_the_ticket, guiding, midground`
（日本語訳：待合室の入口から2人が並んで入ってくる。）

**コマ20: 同じベンチに2人が座り、結が切符を膝の上に置く。**
- 人物・対象: 和紀（Kazuki）、ベンチに座る和紀、両手を膝に置いて座る、待つ、midground / 結（Yui）、隣に座る結、切符を膝の上に置く、穏やか、midground
- 構図: 下段 / medium shot / ベンチ上の2人 / 
- セリフ: kazuki「待ってる。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, small_railway_station_waiting_room, late_afternoon, clear_evening_light, seated, paper_ticket, ticket_on_lap, two_shot, seated_two-shot, both_seated_on_the_bench, medium_shot, two_faces | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, sitting_with_both_hands_on_his_knees, waiting, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, placing_the_ticket_on_her_lap, calm, midground`
（日本語訳：同じベンチに2人が座り、結が切符を膝の上に置く。）

### Step2
カラー漫画、日本の漫画のコマ割り、1ページ2コマ。上段到着・下段着席の2段。numbered panels、読み順は right_to_left。
- コマ10: 上段。待合室の入口から2人が並んで入ってくる。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
- コマ20: 下段。同じベンチに2人が座り、結が切符を膝の上に置く。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote

## Page 2

### Step1
カラー漫画、日本の漫画のコマ割り、1ページ2コマ、読み順: right_to_left
ページ構成: 上段会話・下段出発の2段
共通舞台: small railway station waiting room / late afternoon / 

### Schema 1.1 context
Structured schema 1.1 context:
Lettering Style:
- baseline_direction=vertical; base_font_size=30; size_policy=uniform_then_shrink (post-processing)
Page Purpose and Dramaturgy:
- purpose: Keep the same room and costumes while they finish talking and stand.
- emotional arc: From confirmation to departure.
Panel Dramaturgy and Background Density:
- panel 10: role=continue; purpose=Show that people, place, and costumes match the previous page.; relation_to_previous=Continuation of the seated state.; background_density=medium
- panel 20: role=depart; purpose=Advance motion without changing the place.; relation_to_previous=They stand after the confirmation.; background_density=medium
Character Slots:
- slot_id=p10-s01; panel_id=10; subject_id=p10-s01; character_id=kazuki; variant_id=001_normal; action=looking at Yui beside him; expression=nodding; position=midground
- slot_id=p10-s02; panel_id=10; subject_id=p10-s02; character_id=yui; variant_id=001_normal; action=lifting the ticket from her lap; expression=confirming; position=midground
- slot_id=p20-s01; panel_id=20; subject_id=p20-s01; character_id=kazuki; variant_id=001_normal; action=turning toward the exit still in the jacket; expression=calm; position=midground
- slot_id=p20-s02; panel_id=20; subject_id=p20-s02; character_id=yui; variant_id=001_normal; action=walking with the ticket, still in the cardigan; expression=leading; position=midground
Continuity Tracks:
- entity_id=location; panel_id=10; state=same waiting room as previous page
- entity_id=kazuki; panel_id=10; state=still wearing casual jacket; change_note=costume unchanged from previous page
- entity_id=yui; panel_id=20; state=still wearing cream cardigan and holding ticket
Layout Geometry:
- panel 10: rect=(0.04, 0.03, 0.92, 0.45)
- panel 20: rect=(0.04, 0.52, 0.92, 0.45)
Asset References (ordered attachments when a path is supplied):
- asset_id=kazuki-normal; role=character; character_id=kazuki; attachment=not_requested
- asset_id=yui-normal; role=character; character_id=yui; attachment=not_requested
- asset_id=station-room; role=location; concept_id=station_waiting_room; attachment=not_requested

**コマ10: 前ページと同じベンチで、結が切符を見せながら出発時刻を確認する。**
- 人物・対象: 和紀（Kazuki）、同じジャケットの和紀、隣の結を見る、うなずく、midground / 結（Yui）、同じカーディガンの結、膝の切符を少し持ち上げる、確認、midground
- 構図: 上段 / medium shot / 2人の衣装と切符 / 
- セリフ: yui「もうすぐ。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, small_railway_station_waiting_room, late_afternoon, clear_evening_light, seated, showing_ticket, departure_time, two_shot, seated_two-shot, both_costumes_and_the_ticket, medium_shot, two_faces | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, looking_at_Yui_beside_him, nodding, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, lifting_the_ticket_from_her_lap, confirming, midground`
（日本語訳：前ページと同じベンチで、結が切符を見せながら出発時刻を確認する。）

**コマ20: 同じ待合室で2人が立ち上がり、ホーム側の出口へ向かう。**
- 人物・対象: 和紀（Kazuki）、立ち上がる和紀、ジャケットのまま出口へ向き直る、落ち着き、midground / 結（Yui）、切符を持って立つ結、カーディガンのまま切符を持って歩く、先導、midground
- 構図: 下段 / medium shot / 出口へ向かう2人 / 
- セリフ: kazuki「出よう。」
- **tag**：
`best_quality, very_aesthetic, ultra-detailed, manga, full_color, clean_lineart, small_railway_station_waiting_room, late_afternoon, clear_evening_light, standing, walking_toward_exit, exit_door, two_shot, standing_two-shot, both_heading_to_the_exit, medium_shot, two_faces | Kazuki, 1boy, young_man, black_hair, brown_eyes, fair_skin, tired_but_alert_eyes, smartphone, navy_harrington_jacket, fold_down_collar, zip_front, no_hood, gray_crew_neck_tshirt, dark_navy_straight_pants, turning_toward_the_exit_still_in_the_jacket, calm, midground | Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, button_front, no_hood, white_blouse, brown_plaid_skirt, canvas_tote, walking_with_the_ticket,_still_in_the_cardigan, leading, midground`
（日本語訳：同じ待合室で2人が立ち上がり、ホーム側の出口へ向かう。）

### Step2
カラー漫画、日本の漫画のコマ割り、1ページ2コマ。上段会話・下段出発の2段。numbered panels、読み順は right_to_left。
- コマ10: 上段。前ページと同じベンチで、結が切符を見せながら出発時刻を確認する。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
- コマ20: 下段。同じ待合室で2人が立ち上がり、ホーム側の出口へ向かう。 【固定見た目】和紀: 1boy, young man, black hair, brown eyes, fair skin, tired but alert eyes, smartphone; navy harrington jacket, fold down collar, zip front, no hood, gray crew neck tshirt, dark navy straight pants ｜ 結: 1girl, young woman, brown hair, green eyes, fair skin, small mole near the left eye; cream cardigan, v neck collar, button front, no hood, white blouse, brown plaid skirt, canvas tote
