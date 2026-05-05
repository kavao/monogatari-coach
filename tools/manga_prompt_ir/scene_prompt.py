"""Resolve ``scene`` / panel fields for image prompts: **English tag pipeline**.

``location`` / ``framing`` 等の日本語は人間向けメモとして残せる。
タグ行・txt2img では **``*_en`` を優先**し、旧キーは **CJK を含まない場合のみ** 安全に併用する
（``framing: medium shot`` 等の英語だけの行は従来 YAML でも通る。日本語はタグ列に出さない）。

欠けは各 IR の運用で ``*_en`` を埋めることを推奨する。
"""

from __future__ import annotations

from typing import Any, Mapping


def _has_cjk(s: str) -> bool:
    for ch in s:
        if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def _tag_token_en(
    obj: Mapping[str, Any] | None,
    en_key: str,
    legacy_key: str,
) -> str | None:
    """Prefer ``*_en``; use legacy only when non-empty and contains no CJK."""
    if not obj:
        return None
    raw = obj.get(en_key)
    if raw is not None:
        s = str(raw).strip()
        if s:
            return s
    raw = obj.get(legacy_key)
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or _has_cjk(s):
        return None
    return s


def scene_prompt_location_time_weather(scene: Mapping[str, Any] | None) -> tuple[str, str, str]:
    """Return ``(location_en, time_of_day_en, weather_en)`` for tag lines and step1 text."""
    if not scene:
        return "", "", ""
    return (
        str(scene.get("location_en") or "").strip(),
        str(scene.get("time_of_day_en") or "").strip(),
        str(scene.get("weather_en") or "").strip(),
    )


def scene_prompt_background_notes(scene: Mapping[str, Any] | None) -> str:
    """Return ``background_notes_en`` only (comma-separated English fragments for tags)."""
    if not scene:
        return ""
    raw = scene.get("background_notes_en")
    if raw is None:
        return ""
    return str(raw).strip()


def composition_tag_tokens(composition: Mapping[str, Any] | None) -> list[str]:
    if not composition:
        return []
    out: list[str] = []
    for en_k, leg_k in (
        ("framing_en", "framing"),
        ("focus_en", "focus"),
        ("perspective_en", "perspective"),
    ):
        t = _tag_token_en(composition, en_k, leg_k)
        if t:
            out.append(t)
    return out


def composition_layout_tag_token(
    composition: Mapping[str, Any] | None,
    *,
    single_panel: bool,
) -> list[str]:
    if single_panel or not composition:
        return []
    t = _tag_token_en(composition, "layout_en", "layout")
    return [t] if t else []


def camera_tag_tokens(camera: Mapping[str, Any] | None) -> list[str]:
    if not camera:
        return []
    out: list[str] = []
    for en_k, leg_k in (
        ("angle_en", "angle"),
        ("shot_size_en", "shot_size"),
        ("lens_en", "lens"),
        ("depth_of_field_en", "depth_of_field"),
    ):
        t = _tag_token_en(camera, en_k, leg_k)
        if t:
            out.append(t)
    return out


def lighting_tag_tokens(lighting: Mapping[str, Any] | None) -> list[str]:
    if not lighting:
        return []
    out: list[str] = []
    for en_k, leg_k in (
        ("direction_en", "direction"),
        ("quality_en", "quality"),
        ("mood_effect_en", "mood_effect"),
    ):
        t = _tag_token_en(lighting, en_k, leg_k)
        if t:
            out.append(t)
    return out


def subject_situational_tag_tokens(subject: Mapping[str, Any]) -> list[str]:
    """Pose/expression/position for tag lines (English-only policy)."""
    out: list[str] = []
    for en_k, leg_k in (("pose_action_en", "pose_action"), ("expression_en", "expression")):
        t = _tag_token_en(subject, en_k, leg_k)
        if t:
            out.append(t)
    pos = subject.get("position")
    if pos is not None:
        ps = str(pos).strip()
        if ps and not _has_cjk(ps):
            out.append(ps)
    return out


def panel_mood_atmosphere_tag_tokens(panel: Mapping[str, Any] | None) -> list[str]:
    """``mood_atmosphere_en`` のみ、または CJK を含まない旧 ``mood_atmosphere`` 要素。"""
    if not panel:
        return []
    raw_en = panel.get("mood_atmosphere_en")
    if raw_en is not None:
        if isinstance(raw_en, list):
            return [str(v).strip() for v in raw_en if v and str(v).strip()]
        s = str(raw_en).strip()
        return [s] if s else []
    out: list[str] = []
    for v in panel.get("mood_atmosphere") or []:
        s = str(v).strip()
        if s and not _has_cjk(s):
            out.append(s)
    return out


def subject_tag_line_token(subject: Mapping[str, Any]) -> str:
    """Tag-line token for subjects without ``character_id`` (background/object).

    Prefer ``description_en`` / ``tag_token``. Japanese ``description`` はタグに使わない。
    旧データで description が英語のみの場合のみ許容する。
    """
    raw = subject.get("description_en") or subject.get("tag_token")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    desc = subject.get("description")
    if desc:
        s = str(desc).strip()
        if s and not _has_cjk(s):
            return s
    typ = subject.get("type")
    if typ:
        s = str(typ).strip()
        if s and not _has_cjk(s):
            return s
    return "subject"
