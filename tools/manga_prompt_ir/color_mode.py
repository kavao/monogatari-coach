"""Color mode helpers for manga-prompt-ir pages."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

COLOR_MODE_ENV = "MONOCRI_MANGA_COLOR_MODE_DEFAULT"
VALID_COLOR_MODES = ("monochrome", "limited_color", "full_color")

COLOR_MODE_LABELS = {
    "monochrome": "モノクロ漫画",
    "limited_color": "限定色漫画",
    "full_color": "カラー漫画",
}

COLOR_TOKEN_HINTS = {
    "full_color",
    "full colour",
    "full-color",
    "full colour manga",
    "full color",
    "colorful",
    "colourful",
    "colored",
    "coloured",
    "vivid color",
    "vivid colors",
    "anime coloring",
    "anime colour",
}

MONOCHROME_TOKEN_HINTS = {
    "monochrome",
    "black and white",
    "black-and-white",
    "black_and_white",
    "grayscale",
    "greyscale",
    "screentone",
    "screen tone",
    "screen-tone",
    "screen_tone",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        data = value.model_dump()
        return data if isinstance(data, dict) else {}
    if hasattr(value, "__dict__"):
        return {
            key: val
            for key, val in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _clean_mode(value: Any) -> str | None:
    if value is None:
        return None
    mode = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return mode if mode in VALID_COLOR_MODES else None


def load_dotenv_value(key: str, root: Path | None = None) -> str | None:
    path = (root or repo_root()) / ".env"
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, value = line.split("=", 1)
        if env_key.strip() != key:
            continue
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        return value
    return None


def resolve_color_mode(
    page: Any,
    *,
    override: str | None = None,
    env_default: str | None = None,
    root: Path | None = None,
) -> str:
    """Resolve effective color mode without mutating the page."""
    override_mode = _clean_mode(override)
    if override and not override_mode:
        raise ValueError(
            f"unsupported color mode {override!r}; available: {', '.join(VALID_COLOR_MODES)}"
        )
    if override_mode:
        return override_mode

    data = _as_mapping(page)
    palette = _as_mapping(data.get("color_palette"))
    page_mode = _clean_mode(palette.get("mode"))
    if page_mode:
        return page_mode

    env_mode = _clean_mode(env_default)
    if env_default and not env_mode:
        raise ValueError(
            f"unsupported env color mode {env_default!r}; available: {', '.join(VALID_COLOR_MODES)}"
        )
    if env_mode:
        return env_mode

    process_mode = _clean_mode(os.environ.get(COLOR_MODE_ENV))
    if process_mode:
        return process_mode

    dotenv_mode = _clean_mode(load_dotenv_value(COLOR_MODE_ENV, root=root))
    if dotenv_mode:
        return dotenv_mode

    return "monochrome"


def color_mode_label(mode: str) -> str:
    normalized = _clean_mode(mode)
    if not normalized:
        raise ValueError(
            f"unsupported color mode {mode!r}; available: {', '.join(VALID_COLOR_MODES)}"
        )
    return COLOR_MODE_LABELS[normalized]


def page_color_mode_label(
    page: Any,
    *,
    override: str | None = None,
    env_default: str | None = None,
    root: Path | None = None,
) -> str:
    return color_mode_label(
        resolve_color_mode(page, override=override, env_default=env_default, root=root)
    )


def _norm_token(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[_\s]+", " ", text)
    return text


def _contains_hint(value: Any, hints: set[str]) -> bool:
    token = _norm_token(value)
    dashed = token.replace(" ", "-")
    underscored = token.replace(" ", "_")
    return token in hints or dashed in hints or underscored in hints


def _collect_style_tokens(page: Any) -> list[str]:
    data = _as_mapping(page)
    manga = _as_mapping(data.get("manga"))
    tokens: list[str] = []
    tokens.extend(str(v) for v in _as_list(manga.get("genre_tags")))
    tokens.extend(str(v) for v in _as_list(manga.get("visual_tags")))
    for panel in _as_list(data.get("panels")):
        panel_map = _as_mapping(panel)
        tokens.extend(str(v) for v in _as_list(panel_map.get("prompt_tags")))
    return [token for token in tokens if token]


def _render_instruction_text(page: Any) -> str:
    data = _as_mapping(page)
    instruction = _as_mapping(data.get("render_instruction"))
    parts: list[str] = []
    for key in (
        "prompt_header",
        "task",
        "panel_policy",
        "character_policy",
        "text_policy",
        "output_policy",
    ):
        value = instruction.get(key)
        if value:
            parts.append(str(value))
    parts.extend(str(v) for v in _as_list(instruction.get("notes")) if v)
    return "\n".join(parts)


def validate_color_consistency(
    page: Any,
    *,
    override: str | None = None,
    env_default: str | None = None,
    root: Path | None = None,
) -> list[str]:
    """Return warnings for intentional-review color inconsistencies."""
    mode = resolve_color_mode(page, override=override, env_default=env_default, root=root)
    tokens = _collect_style_tokens(page)
    color_tokens = [t for t in tokens if _contains_hint(t, COLOR_TOKEN_HINTS)]
    mono_tokens = [t for t in tokens if _contains_hint(t, MONOCHROME_TOKEN_HINTS)]
    warnings: list[str] = []

    if mode == "monochrome" and color_tokens:
        warnings.append(
            "color_palette.mode は monochrome ですが、カラー系タグがあります: "
            + ", ".join(dict.fromkeys(color_tokens))
        )
    if mode == "full_color" and mono_tokens:
        warnings.append(
            "color_palette.mode は full_color ですが、モノクロ系タグがあります: "
            + ", ".join(dict.fromkeys(mono_tokens))
        )
    if mode == "limited_color" and color_tokens and mono_tokens:
        warnings.append(
            "color_palette.mode は limited_color です。モノクロ系タグとカラー系タグの併用は"
            "センターカラー等の意図があるか確認してください: "
            + ", ".join(dict.fromkeys(mono_tokens + color_tokens))
        )

    instruction_text = _render_instruction_text(page)
    if instruction_text:
        has_color_instruction = any(
            re.search(pattern, instruction_text, flags=re.IGNORECASE)
            for pattern in (
                r"full[-_\s]?color",
                r"full[-_\s]?colour",
                r"カラー漫画",
                r"フルカラー",
                r"colorful",
                r"colourful",
            )
        )
        has_mono_instruction = any(
            re.search(pattern, instruction_text, flags=re.IGNORECASE)
            for pattern in (
                r"monochrome",
                r"black[-_\s]?and[-_\s]?white",
                r"gr[ae]yscale",
                r"モノクロ",
                r"白黒",
                r"screentone",
            )
        )
        if mode == "monochrome" and has_color_instruction:
            warnings.append(
                "color_palette.mode は monochrome ですが、render_instruction にカラー系の記述があります"
            )
        if mode == "full_color" and has_mono_instruction:
            warnings.append(
                "color_palette.mode は full_color ですが、render_instruction にモノクロ系の記述があります"
            )
    return warnings
