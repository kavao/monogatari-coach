"""改稿工程の脱落（OP-S）。削る前の参照チェックと、物語からの削除の記録だけを行う。

本文の書き換えは行わない。削除そのものは、ユーザーの承認を得たうえで、ON の作品は
refine run の publish、OFF の作品は旧版退避のうえの直接更新で行う。CHRONOS イベントの
削除・未配置への退避は CHRONOS の承認手順で行い、ここでは候補を示すだけである。
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import yaml

from chronos.store import ChronosLoadError, load_store
from inspection_flags import InspectionConfigError, InspectionFlag, load_inspection_flags
from metron.episodes import EpisodeError, load_episodes, locate_span
from metron.storage import atomic_write_text

from .errors import BridgeError
from .links import union_scene_events
from .storage import now_iso
from . import commands

DELETIONS_FILE = "canon_deletions.yaml"
_KATAKANA_RE = re.compile(r"[ァ-ヴー]{2,}")
_CHAPTER_RE = re.compile(r"novel_text(\d+)")
_SCENE_RE = re.compile(r"^ch(\d{2,})-\d{3,}$")


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _chapter_of(path: Path) -> int | None:
    match = _CHAPTER_RE.search(path.stem)
    return int(match.group(1)) if match else None


def _target_text(root: Path, scene_id: str, episode_id: str | None,
                 quote: str | None) -> tuple[str, str, list[str], Path, int]:
    """削る対象と、指定方法によらず重なる契約の持ち帰りを解決する。"""

    if (episode_id is None) == (quote is None):
        raise BridgeError("MISSING_FIELD", "give exactly one of --episode-id or --quote")
    contract_path = root / "_metron" / scene_id / "episodes.yaml"
    episodes = []
    if contract_path.is_file():
        try:
            document = load_episodes(contract_path)
        except (EpisodeError, OSError, ValueError) as error:
            raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid episodes.yaml: {error}") from error
        if document.scene_id != scene_id:
            raise BridgeError("RANGE_MISMATCH", "episodes.yaml belongs to a different scene")
        episodes = document.episodes
    if episode_id is not None:
        episode = next((item for item in episodes if item.id == episode_id), None)
        if episode is None:
            raise BridgeError("UNKNOWN_REF", f"unknown child episode: {episode_id}")
        if episode.span is None:
            raise BridgeError("MISSING_FIELD", f"{episode_id} needs a span to locate the text")
        start_quote, end_quote, label = episode.span.start, episode.span.end, episode_id
    else:
        assert quote is not None  # 冒頭の検査で、episode_id と quote はちょうど片方だけ
        start_quote = end_quote = quote
        label = "quote"
    start_quote = unicodedata.normalize("NFC", start_quote)
    end_quote = unicodedata.normalize("NFC", end_quote)
    hits = []
    for path in sorted((root / "_novel_text").glob("novel_text*.md")):
        text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
        if text.count(start_quote) == 1 and text.count(end_quote) == 1:
            start = text.index(start_quote)
            end = text.index(end_quote) + len(end_quote)
            if end > start:
                hits.append((path, text, start, end))
    if len(hits) != 1:
        raise BridgeError("RANGE_MISMATCH",
                          "the text to strip must be found exactly once in _novel_text")
    path, text, start, end = hits[0]
    used_at = []
    for episode in episodes:
        if not episode.carry_back:
            continue
        if episode.span is None:
            raise BridgeError("MISSING_FIELD",
                              f"{episode.id} needs a span to check protected references")
        try:
            episode_start, episode_end = locate_span(text, episode)
        except EpisodeError as error:
            raise BridgeError("RANGE_MISMATCH",
                              f"cannot locate protected episode: {error}") from error
        if start < episode_end and episode_start < end:
            used_at.extend(f"{item.what} → {item.used_at}" for item in episode.carry_back)
    return text[start:end], label, list(dict.fromkeys(used_at)), path, end


def _chronos_references(root: Path, scene_id: str) -> tuple[list[str], list[str]]:
    """当該場面のイベントと、それを順序・因果で参照する他のイベント。"""

    try:
        flags = load_inspection_flags(root / "config.md")
    except (InspectionConfigError, OSError) as error:
        raise BridgeError("CONFIG_ERROR", str(error)) from error
    if flags.chronos is not InspectionFlag.ON:
        return [], []
    try:
        store = load_store(root)
    except ChronosLoadError as error:
        raise BridgeError("UNKNOWN_REF", str(error)) from error
    own = sorted(union_scene_events(store, scene_id))
    dependents = []
    for event in store.by_id.values():
        if event.id in own:
            continue
        linked = set(event.causes)
        if event.time is not None:
            linked.update(event.time.after)
            linked.update(event.time.before)
        for target in sorted(linked & set(own)):
            dependents.append(f"{event.id}（{event.title}）が {target} を参照")
    return own, dependents


def _term_hits(root: Path, body: str, path: Path, end: int, extra_terms: list[str]) -> list[str]:
    """削る範囲の語が、後の本文と _meta.md に現れるか（補助。意味の参照は著者が判断する）。"""

    terms = list(dict.fromkeys([*_KATAKANA_RE.findall(body), *extra_terms]))
    if not terms:
        return []
    chapter = _chapter_of(path)
    sources: list[tuple[str, str]] = []
    rest = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))[end:]
    sources.append((f"{path.name}（削る範囲より後）", rest))
    for other in sorted((root / "_novel_text").glob("novel_text*.md")):
        number = _chapter_of(other)
        if other != path and chapter is not None and number is not None and number > chapter:
            sources.append((other.name, other.read_text(encoding="utf-8")))
    meta = root / "_meta.md"
    if meta.is_file():
        sources.append(("_meta.md", meta.read_text(encoding="utf-8")))
    hits = []
    for name, text in sources:
        for number, line in enumerate(text.splitlines(), start=1):
            for term in terms:
                if term and term in line:
                    hits.append(f"{name}:{number}: 「{term}」")
    return hits


def _check(root: Path, scene_id: str, episode_id: str | None, quote: str | None):
    if not _SCENE_RE.match(scene_id):
        raise BridgeError("BAD_ID", "invalid scene_id")
    body, label, used_at, path, end = _target_text(root, scene_id, episode_id, quote)
    own, dependents = _chronos_references(root, scene_id)
    extra = [item.split(" → ")[0] for item in used_at]
    hits = _term_hits(root, body, path, end, extra)
    return body, label, used_at, own, dependents, hits


def _render(label, body, used_at, own, dependents, hits) -> str:
    lines = [f"# 脱落（OP-S）の参照チェック: {label}", "", "## 削る対象", "", body.strip(), "",
             "## 持ち帰り（後の場面で使われる）"]
    lines.extend(f"- {item}" for item in used_at or ["なし"])
    lines.extend(["", "## CHRONOS: この場面のイベント（削除・未配置への退避の候補）"])
    lines.extend(f"- {item}" for item in own or ["なし（または CHRONOS OFF）"])
    lines.extend(["", "## CHRONOS: それを参照する他のイベント"])
    lines.extend(f"- {item}" for item in dependents or ["なし"])
    lines.extend(["", "## 後の本文・_meta.md に現れる語（補助）"])
    lines.extend(f"- {item}" for item in hits or ["なし"])
    referenced = bool(used_at or dependents or hits)
    lines.extend(["", "判定: " + ("参照あり。脱落せず、収束（OP-C）に戻す。" if referenced
                                  else "参照なし。ユーザーの承認を得れば脱落できる。"), ""])
    return "\n".join(lines)


def strip_check(work_root: Path, *, scene_id: str, episode_id: str | None = None,
                quote: str | None = None) -> tuple[int, str]:
    """参照があれば終了コード 1。本文・イベントは書き換えない。"""

    root = commands.work_root_of(work_root)
    body, label, used_at, own, dependents, hits = _check(root, scene_id, episode_id, quote)
    report = _render(label, body, used_at, own, dependents, hits)
    return (1 if (used_at or dependents or hits) else 0), report


def strip_record(work_root: Path, *, scene_id: str, reason: str, authorization: str,
                 episode_id: str | None = None, quote: str | None = None) -> tuple[int, str]:
    """承認済みの脱落を物語からの削除として記録する。参照が残っていれば記録しない。"""

    root = commands.work_root_of(work_root)
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the user's approval of the revision step")
    if not reason.strip():
        raise BridgeError("MISSING_FIELD", "record why the events are removed from the story")
    body, label, used_at, own, dependents, hits = _check(root, scene_id, episode_id, quote)
    if used_at or dependents or hits:
        raise BridgeError("STRIP_REFERENCED",
                          "the text is still referenced; condense it (OP-C) instead of stripping",
                          refs={"carry_back": used_at, "dependents": dependents, "terms": hits})
    path = root / "_metron" / scene_id / DELETIONS_FILE
    entries = []
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = list(loaded.get("deletions") or [])
    entry = {"at": now_iso(), "target": label, "text_sha256": _digest(body.strip()),
             "text": body.strip(), "reason": reason, "authorization": authorization,
             "chronos_candidates": own}
    if any(item.get("text_sha256") == entry["text_sha256"] for item in entries):
        return 0, f"deletion already recorded: {path}"
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, yaml.safe_dump({"scene_id": scene_id, "deletions": entries},
                                           allow_unicode=True, sort_keys=False))
    guide = ("next: remove the text with a refine run publish (METRON/CHRONOS ON) or a direct "
             "edit after backup (OFF)")
    if own:
        guide += "; review CHRONOS events " + ", ".join(own) + " through the CHRONOS approval flow"
    return 0, f"deletion recorded: {path}; {guide}"
