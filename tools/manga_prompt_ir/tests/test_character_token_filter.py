"""NovelAI pipe base + tag_csv: drop standalone character_id / name_en tokens."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from image_provider_novel_manga_batch import (  # noqa: E402
    join_novelai_pipe_tag_line,
    yaml_panel_tags,
    yaml_panel_tags_novelai_split,
)
from manga_prompt_ir.character_token_filter import (  # noqa: E402
    collect_blocked_character_tokens,
    filter_base_standalone_character_tokens,
    normalize_character_token_key,
)


def test_normalize_character_token_key() -> None:
    assert normalize_character_token_key("Yuna Tanaka") == "yuna_tanaka"
    assert normalize_character_token_key("yuna") == "yuna"


def test_filter_drops_standalone_id_keeps_phrases() -> None:
    blocked = frozenset({"yuna", "hayate", "yuna_tanaka"})
    base = [
        "establishing_shot",
        "yuna",
        "Yuna Tanaka",
        "Yuna_Tanaka",
        "glowing phone screen",
        "hayate's eyes",
    ]
    out = filter_base_standalone_character_tokens(base, blocked)
    assert out == ["establishing_shot", "glowing phone screen", "hayate's eyes"]


def test_novelai_split_excludes_focus_en_character_id() -> None:
    page = {
        "manga": {"genre_tags": ["manga"]},
        "scene": {"location_en": "bedroom"},
        "character_ids": ["hayate", "yuna"],
        "panels": [],
    }
    panel = {
        "panel_id": 1,
        "summary": "結菜がベッドに横たわる",
        "subjects": [{"character_id": "yuna", "variant_id": "006_nude"}],
        "composition": {"framing_en": "establishing shot", "focus_en": "yuna"},
        "prompt_tags": ["lying_on_back", "dim_lighting"],
    }
    characters = {
        "yuna": {"character_id": "yuna", "name_en": "Yuna Tanaka"},
        "hayate": {"character_id": "hayate", "name_en": "Hayate Tanaka"},
    }
    base, char_segs = yaml_panel_tags_novelai_split(page, panel, characters)
    assert "yuna" not in base
    assert "establishing shot" in base
    assert len(char_segs) == 1
    assert "Yuna_Tanaka" in char_segs[0] or "Yuna Tanaka" in ", ".join(char_segs[0])
    line = join_novelai_pipe_tag_line(base, char_segs)
    assert ", yuna," not in line.split("|")[0]


def test_tag_csv_yaml_panel_tags_excludes_focus_en_character_id() -> None:
    page = {"manga": {}, "scene": {}, "character_ids": ["yuna"]}
    panel = {
        "subjects": [{"character_id": "yuna"}],
        "composition": {"focus_en": "yuna"},
    }
    characters = {"yuna": {"character_id": "yuna", "name_en": "Yuna Tanaka"}}
    tags = yaml_panel_tags(page, panel, characters)
    assert "yuna" not in tags
    assert "Yuna Tanaka" not in tags
    assert "Yuna_Tanaka" not in tags


def test_tag_csv_yaml_panel_tags_excludes_name_en_from_snapshot() -> None:
    page = {
        "manga": {},
        "scene": {},
        "character_ids": ["yuna"],
        "character_snapshots": [
            {
                "character_id": "yuna",
                "name": "結菜",
                "name_en": "Yuna Tanaka",
                "fixed_tags": ["black_hair", "brown_eyes"],
                "variant_tags": ["nude"],
            }
        ],
    }
    panel = {
        "subjects": [{"character_id": "yuna"}],
        "prompt_tags": ["bedroom"],
    }
    tags = yaml_panel_tags(page, panel, {})
    joined = ", ".join(tags)
    assert "Yuna Tanaka" not in joined
    assert "Yuna_Tanaka" not in tags
    assert "yuna" not in tags
    assert "結菜" not in tags
    assert "black_hair" in tags
    assert "brown_eyes" in tags
    assert "nude" in tags


def test_tag_csv_yaml_panel_tags_excludes_name_en_from_character_ir() -> None:
    page = {"manga": {}, "scene": {}, "character_ids": ["yuna"]}
    panel = {"subjects": [{"character_id": "yuna", "variant_id": "000_base"}]}
    characters = {
        "yuna": {
            "character_id": "yuna",
            "name": "結菜",
            "name_en": "Yuna Tanaka",
            "prompt_variants": [
                {
                    "variant_id": "000_base",
                    "danbooru_tags": ["1girl", "black_hair", "brown_eyes"],
                }
            ],
        }
    }
    tags = yaml_panel_tags(page, panel, characters)
    assert "Yuna Tanaka" not in tags
    assert "yuna" not in tags
    assert "black_hair" in tags


def test_collect_blocked_includes_snapshot_names() -> None:
    page = {
        "character_ids": ["yuna"],
        "character_snapshots": [
            {"character_id": "yuna", "name_en": "Yuna Tanaka", "name": "結菜"}
        ],
    }
    blocked = collect_blocked_character_tokens(page, None, {})
    assert "yuna" in blocked
    assert "yuna_tanaka" in blocked
