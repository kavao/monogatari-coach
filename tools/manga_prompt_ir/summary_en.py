"""``panels[].summary_en`` — translation, tag tokens, and quality checks."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Mapping

from manga_prompt_ir.scene_prompt import _has_cjk

SUMMARY_EN_MAX_TAG_CHARS = 220
PIPE_FORBIDDEN = re.compile(r"[|]")


def normalize_summary_text(value: str | None) -> str:
    return str(value or "").strip()


def summary_en_is_stale(panel: Mapping[str, Any]) -> bool:
    summary = normalize_summary_text(panel.get("summary"))
    source = normalize_summary_text(panel.get("summary_en_source"))
    if not summary:
        return False
    if not source:
        return bool(normalize_summary_text(panel.get("summary_en")))
    return source != summary


def needs_summary_en_translation(panel: Mapping[str, Any], *, force: bool = False) -> bool:
    summary = normalize_summary_text(panel.get("summary"))
    if not summary:
        return False
    if force:
        return True
    if not normalize_summary_text(panel.get("summary_en")):
        return True
    return summary_en_is_stale(panel)


def sanitize_summary_en_for_tags(text: str) -> str:
    """NovelAI tag line: one English phrase, no pipe, limited length."""
    s = str(text or "").strip()
    s = PIPE_FORBIDDEN.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    if len(s) > SUMMARY_EN_MAX_TAG_CHARS:
        s = s[: SUMMARY_EN_MAX_TAG_CHARS].rsplit(" ", 1)[0].strip() or s[
            :SUMMARY_EN_MAX_TAG_CHARS
        ]
    return s


def panel_summary_en_tag_tokens(
    panel: Mapping[str, Any] | None,
    *,
    include: bool = True,
) -> list[str]:
    if not include or not panel:
        return []
    raw = normalize_summary_text(panel.get("summary_en"))
    if not raw or _has_cjk(raw):
        return []
    phrase = sanitize_summary_en_for_tags(raw)
    return [phrase] if phrase else []


def summary_en_quality_issues(
    panel: Mapping[str, Any],
    *,
    panel_label: str,
    require_for_manga: bool,
    strict: bool,
) -> tuple[list[str], list[str]]:
    """Return (warnings, errors) for one panel."""
    warnings: list[str] = []
    errors: list[str] = []
    summary = normalize_summary_text(panel.get("summary"))
    summary_en = normalize_summary_text(panel.get("summary_en"))
    prefix = panel_label

    if not summary:
        return warnings, errors

    if not summary_en:
        msg = f"{prefix}: summary がありますが summary_en が空です（novel_manga_panel_summary_en.py で翻訳してください）"
        if require_for_manga and strict:
            errors.append(msg)
        else:
            warnings.append(msg)
    else:
        if _has_cjk(summary_en):
            msg = f"{prefix}: summary_en に日本語（CJK）が含まれています"
            if strict:
                errors.append(msg)
            else:
                warnings.append(msg)
        if len(summary_en) < 8:
            warnings.append(f"{prefix}: summary_en が短すぎる可能性があります ({len(summary_en)} 文字)")

    if summary_en and summary_en_is_stale(panel):
        msg = (
            f"{prefix}: summary が更新されていますが summary_en_source と一致しません "
            f"（再翻訳が必要です）"
        )
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    return warnings, errors


def build_translate_prompt(panels: list[tuple[int, str]]) -> str:
    lines = [
        "Translate each Japanese manga panel summary below into one English sentence "
        "for AI image generation.",
        "Rules:",
        "- Output ONLY valid JSON: an array of objects with keys panel_id (int) and summary_en (string).",
        "- Same panel_id values as input. Same order as listed.",
        "- Keep character names as romaji (e.g. Yuma, Miu).",
        "- No Japanese characters in summary_en. No markdown. No extra keys.",
        "",
        "Panels:",
    ]
    for pid, summary in panels:
        lines.append(f"- panel_id {pid}: {summary}")
    return "\n".join(lines)


def parse_translate_response(raw: str, expected_ids: list[int]) -> dict[int, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("translation response must be a JSON array")
    out: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item["panel_id"])
        except (KeyError, TypeError, ValueError):
            continue
        en = normalize_summary_text(item.get("summary_en"))
        if en:
            out[pid] = en
    missing = [pid for pid in expected_ids if pid not in out]
    if missing:
        raise ValueError(f"translation missing panel_id: {missing}")
    return out


def http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: int,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def extract_chat_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("no choices in chat response")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("invalid message in chat response")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    raise ValueError("empty content in chat response")


def translate_panel_summaries(
    panels: list[tuple[int, str]],
    *,
    api_key: str,
    model: str,
    base_url: str = "https://api.openai.com/v1",
    timeout: int = 120,
) -> dict[int, str]:
    if not panels:
        return {}
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a precise translator for manga production prompts.",
            },
            {"role": "user", "content": build_translate_prompt(panels)},
        ],
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = http_post_json(url, payload, headers=headers, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body[:1500]}") from e
    text = extract_chat_text(response)
    expected = [pid for pid, _ in panels]
    return parse_translate_response(text, expected)
