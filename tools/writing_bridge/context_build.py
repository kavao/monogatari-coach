"""執筆前文脈。CHRONOS の純関数だけを使い、CLI 出力は解析しない。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from chronos.state import format_state_value, is_unknown, resolve_states
from chronos.store import ChronosStore
from metron.contract import load_beat_plan, load_scene_contract
from metron.models import Beat, instruction_target_chars

from .errors import BridgeError
from .hashes import raw_sha256
from .links import union_scene_events
from .models import (
    SCHEMA,
    ContextDocument,
    ExpectedCheck,
    InputHash,
    LinkItem,
    LinksDocument,
    LinksStatus,
    Recorder,
    RequestDocument,
    Selector,
    StateAt,
)
from .paths import resolve_work_path, unit_rel

CONTEXT_USAGE_MARK = "context_usage:"
# ジャンルの芯（genre 葉の小見出し）。行の頭の語が項の名前（計画 20261124_genre-core-notes §4.2）
CORE_SECTION_TITLE = "起草での芯"
CORE_ALWAYS = ("芯の使い方", "避けること")
_CORE_LABEL = re.compile(r"^([^:：\s]{1,30})[:：]\s*")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LEADING_NUMBER = re.compile(r"^[0-9０-９]+[.．)）]?\s*")


def howto_root() -> Path:
    """技法葉のルート。テストから差し替えられるよう関数にしておく。"""
    return Path(__file__).resolve().parents[2]


def _heading_level(line: str) -> int | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    marks = 0
    for char in stripped:
        if char != "#":
            break
        marks += 1
    if marks < 1 or marks > 6:
        return None
    if marks < len(stripped) and stripped[marks] not in " \t":
        return None
    return marks


def _starts_example_block(lines: list[str], index: int) -> bool:
    """箇条書きの見出しの直後が字下げなら、その箇条書きは例の辞書。"""
    if not lines[index].strip().startswith("-"):
        return False
    for line in lines[index + 1 :]:
        if not line.strip():
            continue
        return line.startswith("\t") or line.startswith("    ")
    return False


def _is_usage_mark(line: str) -> bool:
    stripped = line.strip()
    return stripped == CONTEXT_USAGE_MARK or stripped.startswith(f"{CONTEXT_USAGE_MARK} ")


def _open_fence(line: str) -> tuple[str, int] | None:
    """CommonMark の開きフェンス。同一文字が3つ以上。バッククォート開きは情報部に ` を含めない。"""
    stripped = line.strip()
    if len(stripped) < 3 or stripped[0] not in "`~":
        return None
    char = stripped[0]
    length = 0
    for item in stripped:
        if item != char:
            break
        length += 1
    if length < 3:
        return None
    rest = stripped[length:]
    if char == "`" and "`" in rest:
        return None
    return char, length


def _close_fence(line: str, char: str, length: int) -> bool:
    stripped = line.strip()
    run = 0
    for item in stripped:
        if item != char:
            break
        run += 1
    if run < length:
        return False
    return stripped[run:].strip() == ""


def _consume_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """HTML コメントを除いた可視部分。文の途中の `<!--` も対象。"""
    visible: list[str] = []
    rest = line
    while True:
        if in_comment:
            end = rest.find("-->")
            if end < 0:
                return "".join(visible), True
            rest = rest[end + 3 :]
            in_comment = False
            continue
        start = rest.find("<!--")
        if start < 0:
            visible.append(rest)
            return "".join(visible), False
        visible.append(rest[:start])
        rest = rest[start + 4 :]
        in_comment = True


def _inert_mask(lines: list[str]) -> tuple[list[str], list[bool]]:
    """フェンスと HTML コメントは見出しにも印にもしない。コメント内は行から除く。"""
    visible = list(lines)
    inert = [False] * len(lines)
    fence: tuple[str, int] | None = None
    in_comment = False
    for index, raw in enumerate(lines):
        if fence is not None:
            inert[index] = True
            visible[index] = ""
            if _close_fence(raw, fence[0], fence[1]):
                fence = None
            continue
        text, in_comment = _consume_comments(raw, in_comment)
        visible[index] = text
        if not text.strip():
            if in_comment or "<!--" in raw or "-->" in raw:
                inert[index] = True
            continue
        opened = _open_fence(text)
        if opened is not None:
            inert[index] = True
            fence = opened
    return visible, inert


def _clean_note(text: str, title: str) -> str:
    """context 単体で読める形へ直す。葉の中だけの相対リンクと番号を落とす。"""
    text = _MD_LINK.sub(r"\1", text)
    text = text.replace("下の例から", f"技法葉の「{title}」の例から", 1)
    return _LEADING_NUMBER.sub("", text, count=1)


def _notes_from_usage_block(title: str, block: list[str], inert: list[bool]) -> list[str]:
    notes: list[str] = []
    for offset, line in enumerate(block):
        if inert[offset]:
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if _is_usage_mark(line) or stripped.startswith("旧称"):
            continue
        if stripped in {"---", "***", "___"}:
            continue
        if stripped.startswith("#") or line.startswith("\t"):
            break
        if _starts_example_block(block, offset):
            break
        notes.append(_clean_note(stripped, title))
    return notes


def extract_usage_notes(text: str) -> list[str]:
    """selected 葉のうち、context_usage 節の使い方段落だけを取る。例の辞書行は含めない。"""
    lines, inert = _inert_mask(text.splitlines())
    notes: list[str] = []
    index = 0
    while index < len(lines):
        if inert[index] or _heading_level(lines[index]) is None:
            index += 1
            continue
        title = _LEADING_NUMBER.sub("", lines[index].strip().lstrip("#").strip(), count=1)
        index += 1
        start = index
        while index < len(lines):
            if not inert[index] and _heading_level(lines[index]) is not None:
                break
            index += 1
        block = lines[start:index]
        block_inert = inert[start:index]
        if not any(
            _is_usage_mark(line) for line, skip in zip(block, block_inert, strict=True) if not skip
        ):
            continue
        if title == CORE_SECTION_TITLE:
            continue
        notes.extend(_notes_from_usage_block(title, block, block_inert))
    return notes


def extract_core_lines(text: str) -> list[dict[str, str]]:
    """「起草での芯」節の行を、項の名前つきで取る。名前は行の頭の「名前:」。"""
    lines, inert = _inert_mask(text.splitlines())
    out: list[dict[str, str]] = []
    index = 0
    while index < len(lines):
        if inert[index] or _heading_level(lines[index]) is None:
            index += 1
            continue
        title = _LEADING_NUMBER.sub("", lines[index].strip().lstrip("#").strip(), count=1)
        index += 1
        start = index
        while index < len(lines):
            if not inert[index] and _heading_level(lines[index]) is not None:
                break
            index += 1
        if title != CORE_SECTION_TITLE:
            continue
        block = lines[start:index]
        block_inert = inert[start:index]
        if not any(_is_usage_mark(line) for line, skip in zip(block, block_inert, strict=True) if not skip):
            continue
        for note in _notes_from_usage_block(title, block, block_inert):
            match = _CORE_LABEL.match(note)
            out.append({"label": match.group(1) if match else "", "text": note})
    return out


def select_core_lines(core_lines: list[dict[str, str]], beat_core: list[str] | None) -> list[dict[str, str]]:
    """Beat の core に合う行。None は全部、[] は常に載せる行だけ。名前の無い行はいつも載せる（黙って落とさない）。"""
    if beat_core is None:
        return list(core_lines)
    wanted = set(beat_core) | set(CORE_ALWAYS)
    return [line for line in core_lines if not line.get("label") or line.get("label") in wanted]


def _is_expression_leaf(relative_id: str, path: Path) -> bool:
    name = relative_id.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name == "expression.md" or path.name.lower() == "expression.md"


def _expression_mix_on(work_root: Path) -> bool:
    meta = work_root / "_meta.md"
    if not meta.is_file():
        return False
    try:
        from novel_expression_mix import mix_is_enabled
    except ImportError:
        return False
    try:
        return mix_is_enabled(meta.read_text(encoding="utf-8"))
    except OSError:
        return False


def _selected_leaf_texts(work_root: Path) -> list[tuple[str, str]]:
    """契約の selected 葉の (relative_id, 本文)。表現ミックスが OFF なら expression.md を除く。"""
    meta = work_root / "_meta.md"
    if not meta.is_file():
        return []
    try:
        from novel_howto_contract_check import check_novel, resolve_effective
    except ImportError:
        return []
    root = howto_root()
    try:
        result = check_novel(work_root, root)
    except (OSError, ValueError):
        return []
    mix_on = _expression_mix_on(work_root)
    texts: list[tuple[str, str]] = []
    for item in result.selected:
        path, errors = resolve_effective(item, root, new_format=result.format == "new")
        if errors or path is None or not path.is_file():
            continue
        if _is_expression_leaf(item.relative_id, path) and not mix_on:
            continue
        try:
            texts.append((item.relative_id, path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return texts


def load_selected_usage(work_root: Path) -> list[str]:
    """契約の selected 葉から、使い方段落を集める（ジャンルの芯の節は除く）。"""
    notes: list[str] = []
    for _, text in _selected_leaf_texts(work_root):
        notes.extend(extract_usage_notes(text))
    return notes


def load_selected_core(work_root: Path) -> list[dict[str, str]]:
    """契約の selected 葉から、ジャンルの芯の行を集める（葉の relative_id を source に残す）。"""
    lines: list[dict[str, str]] = []
    for relative_id, text in _selected_leaf_texts(work_root):
        for line in extract_core_lines(text):
            lines.append({**line, "source": relative_id})
    return lines


def peek_model_calibrated(config_path: Path, model_id: str) -> bool:
    if not config_path.is_file():
        return False
    try:
        from metron.storage import load_yaml

        models = load_yaml(config_path).get("models")
        if not isinstance(models, dict):
            return False
        raw = models.get(model_id)
        return isinstance(raw, dict) and raw.get("calibrated") is True
    except (OSError, ValueError):
        return False


def collect_input_hashes(work_root: Path, rel_paths: list[str]) -> list[InputHash]:
    hashes: list[InputHash] = []
    for rel in rel_paths:
        path = resolve_work_path(work_root, rel)
        if path.is_file():
            hashes.append(InputHash(path=rel, raw_sha256=raw_sha256(path)))
    return hashes


def build_candidate_links(
    request: RequestDocument,
    store: ChronosStore,
    selector: Selector,
    text_sha: str,
) -> LinksDocument:
    items: list[LinkItem] = []
    for event_id in sorted(union_scene_events(store, request.scene_id)):
        event = store.by_id[event_id]
        actors = list(event.actors) or []
        if not actors:
            continue
        items.append(
            LinkItem(
                event_id=event_id,
                state_at=StateAt.AFTER,
                actors=actors,
            )
        )
    return LinksDocument(
        schema=SCHEMA,
        scene_id=request.scene_id,
        text_path=request.target.text_path,
        selector=selector,
        text_sha256=text_sha,
        status=LinksStatus.CANDIDATE,
        created_by=Recorder.TOOL,
        adopted_by=Recorder.TOOL,
        items=items,
    )


def build_context(
    work_root: Path,
    request: RequestDocument,
    *,
    store: ChronosStore | None,
    links: LinksDocument | None,
    metron_root: Path | None,
    extra_hashes: list[str],
) -> ContextDocument:
    unresolved: list[dict[str, Any]] = []
    expected: list[ExpectedCheck] = []
    states: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    forbidden: list[str] = []
    instruction = None
    chars_floor = None
    prose = None

    if request.flags.metron.value == "ON":
        if metron_root is None or not (metron_root / "contract.yaml").is_file():
            raise BridgeError(
                "UNKNOWN_REF",
                "METRON is ON but contract.yaml is missing",
                refs={"path": unit_rel(work_root, "metron", request.scene_id, "contract.yaml")},
            )
        if not (metron_root / "beats.yaml").is_file():
            raise BridgeError(
                "UNKNOWN_REF",
                "METRON is ON but beats.yaml is missing",
                refs={"path": unit_rel(work_root, "metron", request.scene_id, "beats.yaml")},
            )
        contract = load_scene_contract(metron_root / "contract.yaml")
        plan = load_beat_plan(metron_root / "beats.yaml")
        if contract.scene.id != request.scene_id:
            raise BridgeError(
                "UNKNOWN_REF",
                "contract scene.id does not match request",
                refs={"contract": contract.scene.id, "request": request.scene_id},
            )
        forbidden = list(contract.scene.forbidden)
        instruction = instruction_target_chars(plan.generation.chars_floor)
        chars_floor = plan.generation.chars_floor
        beats = [_beat_context_entry(beat) for beat in plan.beats]
        start = contract.scene.start_state
        end = contract.scene.end_state
        if start or end:
            prose = {
                "start_location": start.location if start else None,
                "end_location": end.location if end else None,
                "note": "散文。CHRONOS の loc_ref へ変換しない",
            }

    if request.flags.chronos.value == "ON":
        if store is None:
            raise BridgeError("UNKNOWN_REF", "CHRONOS is ON but chronos/ was not loaded")
        resolution = resolve_states(store)
        event_ids = _linked_or_scene_events(store, request.scene_id, links)
        if resolution.skipped_all:
            unresolved.append(
                {
                    "reason": resolution.skip_reason,
                    "note": "state was not invented",
                }
            )
        for event_id in sorted(event_ids):
            event = store.by_id.get(event_id)
            if event is None:
                unresolved.append({"event_id": event_id, "reason": "UNKNOWN_REF"})
                continue
            for actor_id in event.actors:
                actor = resolution.actors.get(actor_id)
                if actor is None or actor.skip_reason or actor.events is None:
                    unresolved.append(
                        {
                            "event_id": event_id,
                            "actor_id": actor_id,
                            "reason": actor.skip_reason if actor else "unresolved",
                        }
                    )
                    continue
                snapshot = next((item for item in actor.events if item.event_id == event_id), None)
                if snapshot is None:
                    unresolved.append(
                        {
                            "event_id": event_id,
                            "actor_id": actor_id,
                            "reason": "event not in resolved actor timeline",
                        }
                    )
                    continue
                states.append(
                    {
                        "event_id": event_id,
                        "actor_id": actor_id,
                        "before": {key: format_state_value(value) for key, value in snapshot.before.items()},
                        "after": {key: format_state_value(value) for key, value in snapshot.after.items()},
                        "changed": list(snapshot.changed),
                    }
                )
                explicit = (event.effects_on or {}).get(actor_id) or {}
                for name in snapshot.changed:
                    value = snapshot.after.get(name)
                    if is_unknown(value):
                        unresolved.append(
                            {
                                "event_id": event_id,
                                "actor_id": actor_id,
                                "dimension": name,
                                "reason": "unknown",
                            }
                        )
                        continue
                    if name not in explicit:
                        continue
                    expected.append(
                        ExpectedCheck(
                            event_id=event_id,
                            actor_id=actor_id,
                            dimension=name,
                            state_at=StateAt.AFTER,
                            expected_value=_json_value(value),
                        )
                    )

    return ContextDocument(
        schema=SCHEMA,
        request_id=request.request_id,
        run_id=request.run_id,
        input_hashes=collect_input_hashes(work_root, extra_hashes),
        expected_checks=expected,
        beats=beats,
        forbidden=forbidden,
        instruction_chars=instruction,
        chars_floor=chars_floor,
        craft_notes=load_selected_usage(work_root),
        core_lines=load_selected_core(work_root),
        states=states,
        unresolved=unresolved,
        prose_start_end=prose,
    )


def _linked_or_scene_events(
    store: ChronosStore,
    scene_id: str,
    links: LinksDocument | None,
) -> set[str]:
    if links and links.items:
        return {item.event_id for item in links.items}
    return union_scene_events(store, scene_id)


def _json_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    return str(value)


def _budget_bounds(bounds: tuple[int, int | None]) -> list[int | None]:
    return [bounds[0], bounds[1]]


def _range_text(bounds: list[int | None] | tuple[int, int | None]) -> str:
    lower, upper = bounds[0], bounds[1]
    if upper is None:
        return f"{lower}-無制限"
    return f"{lower}-{upper}"


def _beat_context_entry(beat: Beat) -> dict[str, Any]:
    hint = beat.budget.chars_hint
    return {
        "id": beat.id,
        "type": beat.type,
        "intent": beat.intent,
        "chars_hint": hint,
        "chars_floor": hint,
        "chars_instruction": instruction_target_chars(hint),
        "paragraphs": _budget_bounds(beat.budget.paragraphs),
        "dialogue_turns": _budget_bounds(beat.budget.dialogue_turns),
        "sensory": beat.budget.sensory,
        "interiority": beat.budget.interiority,
        "advisory": True,
        "expandable": beat.expandable,
        "core": list(beat.core) if beat.core is not None else None,
    }


def _core_text(core: list[str] | None, known: set[str | None]) -> str | None:
    """Beat の芯の表示。欄なしは None（各行の場面で選ぶ）。"""
    if core is None:
        return None
    if not core:
        return "芯: 使わない"
    names = [name if name in known else f"{name}（芯に無い項）" for name in core]
    return "芯: " + "・".join(names)


def render_context_md(context: ContextDocument) -> str:
    lines = [
        f"# context {context.request_id}",
        "",
    ]
    if context.chars_floor is not None:
        lines.append(f"chars_floor: {context.chars_floor}")
    lines.append(f"instruction_chars: {context.instruction_chars}")
    if context.instruction_chars is not None:
        lines.append("instruction_chars は助言（検査床ではない）。初稿は指示目標以上を1回で書く。床ちょうどは狙わない。")
    lines.extend(
        [
            f"expected_checks: {len(context.expected_checks)}",
            f"unresolved: {len(context.unresolved)}",
            "",
        ]
    )
    if context.forbidden:
        lines.append("forbidden: " + ", ".join(context.forbidden))
        lines.append("")
    if context.craft_notes:
        lines.append("技法の使い方:")
        lines.append("- 語の例は技法葉にあり、この context には載せない。")
        lines.extend(f"- {note}" for note in context.craft_notes)
        lines.append("")
    if context.core_lines:
        lines.append("ジャンルの芯（Beat に「芯:」があればその項と、芯の使い方・避けることだけを使う。無ければ各行の場面で選ぶ）:")
        lines.extend(f"- {line['text']}" for line in context.core_lines)
        lines.append("")
    known_core = {line.get("label") for line in context.core_lines}
    for beat in context.beats:
        intent = beat.get("intent")
        floor = beat.get("chars_floor", beat.get("chars_hint"))
        target = beat.get("chars_instruction")
        paragraphs = _range_text(beat["paragraphs"]) if beat.get("paragraphs") else "-"
        dialogue = _range_text(beat["dialogue_turns"]) if beat.get("dialogue_turns") else "-"
        extras = [f"段落{paragraphs}", f"会話{dialogue}"]
        if beat.get("sensory") is not None:
            extras.append(f"感覚{beat['sensory']}")
        if beat.get("interiority") is not None:
            extras.append(f"内面{beat['interiority']}")
        core_text = _core_text(beat.get("core"), known_core) if context.core_lines else None
        if core_text:
            extras.append(core_text)
        extra = " / ".join(extras)
        if target is not None:
            lines.append(
                f"- beat {beat.get('id')}: {intent} / 下限{floor} / 目標{target}（助言） / {extra}"
            )
        else:
            tail = f" / {core_text}" if core_text else ""
            lines.append(f"- beat {beat.get('id')}: {intent}{tail}")
    if context.prose_start_end:
        lines.append("")
        lines.append("prose_start_end は CHRONOS 値ではない。")
    return "\n".join(lines) + "\n"
