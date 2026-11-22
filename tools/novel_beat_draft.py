#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
低コンテキストの書き手に、Beat ごとに続きを書かせ、候補から機械で1本を選んで章の作業稿を組み立てる。

計画 _workingspace/plans/20261114_model-adaptive-writing-support.md §23.4・§24（試行の条件 G を正規にしたもの）。

手順（1つの run の Beat を順に）:
  1. 資料を組む。量は「章に要る部分」にそろえる（禁止事項、執筆方針、設計書のテーマ・コンセプト・主軸と当該章、
     人物資料から身長・ワンポイント特徴・外見の個性・服装を外したもの、当該章までの用語、用語の書き方の規則5・6、
     --leaf で渡した葉）。見せ方軸は渡さない。人物の外見の行は、その人物が初めて出る Beat にだけ入れる。
  2. 「これまでの本文」の全文と、次に書く出来事（Beat の intent）と字数（Beat の指示目標 chars_instruction。
     無ければ床）を添え、候補を --candidates 本書かせる。
  3. これまでの本文と12字以上一致する候補、すでに出た人物の外見と6字以上一致する候補、
     後の Beat の intent と8字以上一致して今の intent に無い候補（先取り）、場面契約で「〇〇という語を書く
     こと」と禁じた語を含む候補を外し、
     残りを「癖外見の写し/10 ＋ の連鎖％/2 ＋ 結論告げ×2」（目安の8割に届かない分を減点）で選ぶ。
     全部外れたら外れの理由の少ない候補を採り、その文だけで理由に当たる文（台詞は一続きの「」）を削って、
     selection.json に「全落ち」と削った文を残す。削って足りなくなった字数は言い換えで埋めない
     （床までの不足を selection.json の shortfall に出し、inspect のあと加筆工程か Deepen へ回す）。
  4. Beat マーカー付きで連結し、run の beat_draft/draft.md に置く。

- 先に writing_bridge の prepare で run を作っておく。書き手は run の request.yaml の model.id で
  config/writer_profiles.yaml を引き、tier が low_context のときだけ動く。
- 本文の正本（_novel_text/）には書かない。続きは writing_bridge の receive → inspect → publish で行う（このツールは呼ばない）。
- 途中で止まったら、同じコマンドをもう一度実行する。保存済みの候補は書き直さずに使う。
- --relay: 書き手を呼ばない（backend が未接続の書き手、たとえば Cursor で動かす Grok 4.6 に使う）。
  足りない候補があれば、その Beat のプロンプトと候補の置き場を出して止まる。人が候補を置いて再実行すると、
  選んで次の Beat のプロンプトを書く。外部への送信はこのツールでは行わない。

終了コード: 0 = 組み立てた（plan は表示した） / 1 = 書き手の誤り / 2 = 引数・作品・run・設定の誤り / 3 = 中継の候補待ち
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prose_signals as ps  # noqa: E402
from novel_glossary import first_chapter_in  # noqa: E402
from novel_punctuation_metrics import measure_text  # noqa: E402
from writer_profiles import UNSPECIFIED_IDS, WriterProfile, WriterProfileError, get_profile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = "beat_draft"
DROP_FIELDS = ("身長", "ワンポイント特徴", "外見の個性", "服装")
DESIGN_SECTIONS = ("テーマ", "コンセプト", "主軸と進行条件")
APPEARANCE_LABEL = "外見（初めて出る場面で一度だけ書く）"
# DESIGN_DENSITY のときに読む工程正本（子エピソードの挿し方と、設計へ足す手順）
SUB_EPISODE_LEAF = "_how_to.example/episode/general/episode_sub_episode.md"
LENGTH_OPS = "_how_to.example/length_ops.md"

Writer = Callable[..., dict[str, Any]]


class BeatDraftError(RuntimeError):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


# ── 資料 ────────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def section(text: str, heading_re: str, level: int) -> str:
    """見出し（level 個の # と heading_re に合う題）から、同格以上の次の見出しまで。無ければ空。"""
    lines = text.splitlines()
    pat = re.compile(rf"^{'#' * level}\s+{heading_re}\s*$")
    start = next((i for i, l in enumerate(lines) if pat.match(l.strip())), None)
    if start is None:
        return ""
    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#+)\s", lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def chapter_number(scene_id: str) -> int:
    m = re.match(r"^ch(\d+)", scene_id)
    if not m:
        raise BeatDraftError(f"scene_id から章番号を取れない（chNN-… の形にする）: {scene_id}")
    return int(m.group(1))


def chapter_heading(design: str, chapter: int) -> tuple[str, str]:
    """設計書の「第N章」の見出しの題と、その節。無ければ（第N章, 空）。"""
    for level in (2, 3, 4):
        pat = re.compile(rf"^{'#' * level}\s+(第\s*{chapter}\s*章.*)$")
        for line in design.splitlines():
            m = pat.match(line.strip())
            if m:
                return m.group(1).strip(), section(design, re.escape(m.group(1).strip()), level)
    return f"第{chapter}章", ""


def characters_reduced(character_md: str, show: set[str]) -> str:
    """外見の個性・服装などの欄（と、その下の箇条書き）を外す。外見は show の人物だけに残す。"""
    out: list[str] = []
    skipping = False
    current: str | None = None
    for line in character_md.splitlines():
        heading = ps.HEADING_RE.match(line)
        if heading:
            current = heading.group(1)
            skipping = False
            out.append(line)
            continue
        if line.startswith("#"):
            skipping = False
            out.append(line)
            continue
        m = ps.FIELD_RE.match(line)
        if m:
            name = m.group(1)
            skipping = name in DROP_FIELDS or (name == "外見" and current not in show)
            if name == "外見" and not skipping:
                line = line.replace("- **外見**:", f"- **{APPEARANCE_LABEL}**:", 1)
        if not skipping:
            out.append(line)
    return "\n".join(out).strip()


def world_reduced(world_md: str, chapter: int) -> str:
    out = []
    for line in world_md.splitlines():
        first = first_chapter_in(line)  # 用語ツールと同じ判定（「初出: 第N章」「第N章で初出」）
        if first is not None and first > chapter:
            continue
        out.append(line)
    return "\n".join(out).strip()


def glossary_rules() -> str:
    for rel in ("_how_to/world_glossary.md", "_how_to.example/world_glossary.md"):
        text = _read(ROOT / rel)
        if text:
            keep = [l for l in text.splitlines() if re.match(r"^(5|6)\. \*\*", l)]
            if keep:
                return "# 用語の書き方（抜粋）\n\n" + "\n".join(keep)
    return ""


@dataclass
class Materials:
    work: Path
    chapter: int
    title_line: str
    forbidden: list[str]
    character_md: str
    parts_before_characters: list[str]
    parts_after_characters: list[str]
    names: list[str] = field(default_factory=list)

    def background(self, show: set[str]) -> str:
        parts = ["# 資料"]
        if self.forbidden:
            parts.append("forbidden: " + ", ".join(self.forbidden))
        parts += self.parts_before_characters
        parts.append(characters_reduced(self.character_md, show))
        parts += self.parts_after_characters
        return "\n\n---\n\n".join(p for p in parts if p)


def build_materials(work: Path, scene_id: str, forbidden: list[str], leaves: list[Path]) -> Materials:
    chapter = chapter_number(scene_id)
    design = _read(work / "design_specification.md")
    character_md = _read(work / "character.md")
    if not character_md:
        raise BeatDraftError(f"character.md が無い: {work}")
    heading, chapter_section = chapter_heading(design, chapter)
    design_parts = [s for s in (section(design, re.escape(h), 2) for h in DESIGN_SECTIONS) if s]
    if chapter_section:
        design_parts.append(chapter_section)
    before = [section(_read(work / "config.md"), "執筆方針", 2)]
    if design_parts:
        before.append(f"# 小説設計書（第{chapter}章に要る部分）\n\n" + "\n\n".join(design_parts))
    after = [world_reduced(_read(work / "world.md"), chapter)]
    leaf_texts = []
    for leaf in leaves:
        path = leaf if leaf.is_absolute() else ROOT / leaf
        if not path.is_file():
            raise BeatDraftError(f"--leaf のファイルが無い: {leaf}")
        leaf_texts.append(_read(path))
    if leaf_texts:
        after.append("# 創作技法（起草で使う葉）\n\n" + "\n\n".join(leaf_texts))
    after.append(glossary_rules())
    return Materials(
        work=work,
        chapter=chapter,
        title_line=f"# {heading}",
        forbidden=forbidden,
        character_md=character_md,
        parts_before_characters=before,
        parts_after_characters=after,
        names=list(ps.character_blocks(character_md)),
    )


def first_beats(beats: list[dict[str, Any]], names: list[str]) -> dict[str, int]:
    """人物ごとに、名前が intent に初めて出る Beat の番号（0 始まり）。"""
    first: dict[str, int] = {}
    for i, beat in enumerate(beats):
        for name in names:
            if name in str(beat.get("intent", "")) and name not in first:
                first[name] = i
    return first


_REQUEST_MARK = "\n---\n\n# 依頼\n\n"
_BUDGET_LINE_RE = re.compile(
    r"^(会話の往復数: .+|感覚描写: 少なくとも \d+ 箇所|内面描写: 少なくとも \d+ 箇所)\n",
    re.M,
)
_CRAFT_BLOCK_RE = re.compile(r"^技法の使い方:\n(?:- .+\n)*\n?", re.M)


def _prompt_head_tail(prompt: str) -> tuple[str, str]:
    text = prompt.replace("\r\n", "\n")
    index = text.find(_REQUEST_MARK)
    if index < 0:
        return text, ""
    split = index + len(_REQUEST_MARK)
    return text[:split], text[split:]


def _strip_budget_lines(tail: str) -> str:
    return _BUDGET_LINE_RE.sub("", tail)


def prompt_for_stale_compare(prompt: str) -> str:
    """資料比較用。予算行と技法メモは除く。"""
    head, tail = _prompt_head_tail(prompt)
    tail = _CRAFT_BLOCK_RE.sub("", _strip_budget_lines(tail))
    return head + re.sub(r"\n{3,}", "\n\n", tail)


def _prompt_craft_block(prompt: str) -> str | None:
    _, tail = _prompt_head_tail(prompt)
    match = _CRAFT_BLOCK_RE.search(_strip_budget_lines(tail))
    if match is None:
        return None
    return match.group(0)


def is_stale_saved_prompt(saved: str, new: str) -> bool:
    """旧版は技法メモをプロンプトへ出していなかった。メモが無かった旧稿へ新版が同じメモを足す差は資料変更にしない。"""
    if prompt_for_stale_compare(saved) != prompt_for_stale_compare(new):
        return True
    saved_notes = _prompt_craft_block(saved)
    if saved_notes is None:
        return False
    return saved_notes != _prompt_craft_block(new)


def _range_ja(bounds: Any) -> str | None:
    if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
        return None
    lower, upper = bounds[0], bounds[1]
    return f"{lower}〜{upper if upper is not None else '上限なし'}"


def beat_prompt(
    materials: Materials,
    show: set[str],
    prior: str,
    beat: dict[str, Any],
    hint: int,
    first: bool,
    *,
    craft_notes: list[str] | None = None,
) -> str:
    story = f"（まだない。第{materials.chapter}章の書き出しから書く）" if first else prior
    extras: list[str] = []
    turns = _range_ja(beat.get("dialogue_turns"))
    if turns:
        extras.append(f"会話の往復数: {turns}")
    if beat.get("sensory") is not None:
        extras.append(f"感覚描写: 少なくとも {beat['sensory']} 箇所")
    if beat.get("interiority") is not None:
        extras.append(f"内面描写: 少なくとも {beat['interiority']} 箇所")
    extra_block = ("\n".join(extras) + "\n\n") if extras else ""
    notes_block = ""
    if craft_notes:
        notes_block = "技法の使い方:\n" + "\n".join(f"- {note}" for note in craft_notes) + "\n\n"
    return (
        materials.background(show)
        + "\n\n---\n\n# これまでの本文\n\n"
        + story
        + "\n\n---\n\n# 依頼\n\n"
        + "あなたは小説の書き手です。「これまでの本文」の続きを書いてください。\n\n"
        + f"次に書く出来事：{beat.get('intent')}\n\n"
        + extra_block
        + notes_block
        + f"この出来事だけを書き、その先の出来事へ進まない。およそ{hint}字。"
        + "地の文の段落は頭を全角空白で始める。会話の行は空白を付けず「から始める。本文だけを出力する。\n"
    )


# ── 判定 ────────────────────────────────────────────────────────────


def clean(text: str) -> str:
    """書き手が付けた見出しとマーカーを外し、会話の行の頭に付いた空白を外す（体裁だけ。字は変えない）。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = (DIALOGUE_INDENT_RE.sub("", l) for l in text.strip("\n").splitlines() if not l.startswith("#"))
    return "\n".join(lines).strip("\n")


def score(text: str, hint: int, phrases: list[str]) -> dict[str, Any]:
    narr = ps.narration(text)
    trait = ps.trait_copy_per_k(narr, phrases)
    tell = ps.tell_per_k(narr)
    # 地の文が無い（会話だけの）候補は、連鎖の無い文も無いので 0 とする
    chain = (measure_text(text)["no_chain_sentence_rate"] or 0) * 100
    short = max(0.0, hint * 0.8 - len(narr)) / 100
    return {
        "chars": len(narr),
        "trait_per_k": round(trait, 1),
        "tell_per_k": round(tell, 1),
        "no_chain_pct": round(chain, 1),
        "total": round(trait / 10 + chain / 2 + tell * 2 + short, 2),
    }


UNIT_RE = re.compile(r"「[^」]*」|『[^』]*』|[^。「」『』]+。?")
DIALOGUE_INDENT_RE = re.compile(r"^[　 ]+(?=[「『])")
REASON_KEYS = ("overlaps", "redescribed", "lookahead", "forbidden", "repeats")


def cut_copies(
    text: str,
    prior: str,
    introduced: set[str],
    appearance: dict[str, str],
    *,
    later: str = "",
    current: str = "",
    terms: list[str] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """全落ちの候補から、その文（台詞は一続きの「」）だけで外れの理由に当たるものを削る。

    削るのは、これまでの本文と12字以上一致する文、すでに出た人物の外見を描き直した文、
    後の Beat の出来事を先に書いた文（先取り）、書かないと決めた語を含む文、
    同じ形の台詞が場面で3回目以上になる台詞（口癖の繰り返し）だけ。
    隣の文とつながって初めて一致する文は残す。足りなくなった字数は言い換えで埋めない（加筆工程か Deepen へ回す）。
    """
    removed: list[dict[str, str]] = []
    paragraphs = []
    said = prior  # 口癖の数え先: これまでの本文と、この候補で残した台詞
    for para in text.split("\n"):
        indent = "　" if para.startswith("　") else ""
        kept = []
        for unit in UNIT_RE.findall(para.strip("　 ")):
            if not unit.strip():
                continue
            ov = ps.overlaps(unit, prior)
            rd = ps.redescribed(unit, introduced, appearance)
            la = ps.lookahead(unit, later, current, prior) if later else []
            fb = ps.forbidden_hits(unit, terms or [])
            rp = ps.repeated_lines(unit, said) if unit.startswith("「") else []
            if ov:
                reason = "前の本文と一致:" + ov[0]
            elif rd:
                reason = "外見の描き直し:" + rd[0]
            elif la:
                reason = "先取り:" + la[0]
            elif fb:
                reason = "書かない語:" + fb[0]
            elif rp:
                reason = "口癖の繰り返し:" + rp[0]
            else:
                kept.append(unit)
                said += "\n" + unit
                continue
            removed.append({"sentence": unit, "reason": reason})
        if kept:
            paragraphs.append(indent + "".join(kept))
    return "\n".join(paragraphs), removed


def _saved_finish_reason(path: Path) -> str | None:
    """保存済みの候補の finish_reason（書き手を呼んだときの記録。中継で置いた候補には無い）。"""
    meta = path.with_suffix(".json")
    if not meta.is_file():
        return None
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("finish_reason")
    except (OSError, ValueError):
        return None


def choose(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    """外れていない候補から total の小さいもの。全部外れたら外れの理由の少ないもの（fallback=True）。"""
    ok = [r for r in rows if not r["rejected"]]
    if ok:
        return min(ok, key=lambda r: r["total"]), False
    rows = [r for r in rows if not r.get("truncated")] or rows  # 打切りの候補は、削って採る対象にもしない

    def misses(r: dict[str, Any]) -> int:
        return sum(len(r.get(k) or []) for k in REASON_KEYS)

    return min(rows, key=lambda r: (misses(r), r["total"])), True


# ── 実行 ────────────────────────────────────────────────────────────


def _run_paths(work: Path, scene_id: str, run_id: str) -> Path:
    from writing_bridge.commands import run_dir

    path = run_dir(work, scene_id, run_id)
    if not (path / "request.yaml").is_file() or not (path / "context.json").is_file():
        raise BeatDraftError(f"run が無いか、request.yaml / context.json が無い（先に writing_bridge の prepare）: {path}")
    return path


def load_run(work: Path, scene_id: str, run_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    run = _run_paths(work, scene_id, run_id)
    request = yaml.safe_load((run / "request.yaml").read_text(encoding="utf-8")) or {}
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    if not context.get("beats"):
        raise BeatDraftError(f"context.json に Beat が無い: {run}")
    return run, request, context


def resolve_writer(request: dict[str, Any], *, relay: bool = False) -> tuple[WriterProfile, Writer | None]:
    """書き手の段を引き、呼び出し方を決める。relay=True は書き手を呼ばない（候補は人がほかの道具で作る）。"""
    model_id = str((request.get("model") or {}).get("id") or "")
    if model_id in UNSPECIFIED_IDS:
        raise BeatDraftError(
            f"run の書き手 {model_id!r} は prepare の既定の名前で、書き手を表さない。"
            "低コンテキストの書き手で書くときは、config/writer_profiles.yaml の名前を prepare --model に渡して run を作り直す")
    try:
        profile = get_profile(model_id)
    except WriterProfileError as error:
        raise BeatDraftError(str(error)) from error
    if profile is None:
        raise BeatDraftError(f"書き手 {model_id!r} が config/writer_profiles.yaml に無い（段を作者が決めてから登録する）")
    if profile.tier != "low_context":
        raise BeatDraftError(f"書き手 {model_id!r} の段は {profile.tier}。このツールは low_context の書き手だけに使う")
    if relay:
        return profile, None
    if profile.backend == "local_openai":
        import local_writer_cli

        return profile, local_writer_cli.complete
    raise BeatDraftError(
        f"書き手 {model_id!r} の backend {profile.backend} はまだ接続していない"
        "（外部への送信になるため、作者の明示の承認と接続の実装が要る）。"
        "人がほかの道具（Cursor など）で候補を作るときは --relay を付ける"
    )


def density_check(context: dict[str, Any], beats: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """指示目標（余地込みの目標）に対する不足率。10%以上は Deepen ではなく、出来事を足す設計追加へ回す（D21）。

    writing_bridge の自動修復は床と比べるだけなので、ここで指示目標と Beat ごとの不足も見る（計画 §24.6）。
    知らせるだけで、設計も本文も変えない。
    """
    from metron.length import DESIGN_SHORTAGE_LIMIT, shortage_ratio

    scene_target = int(context.get("instruction_chars")
                       or sum(int(b.get("chars_instruction") or b.get("chars_hint") or 0) for b in beats))
    scene_chars = sum(r["chars"] for r in rows)
    scene_ratio = shortage_ratio(scene_target, scene_chars)
    beat_rows = []
    for beat, row in zip(beats, rows):
        target = int(beat.get("chars_instruction") or beat.get("chars_hint") or 0)
        ratio = shortage_ratio(target, row["chars"])
        if ratio >= DESIGN_SHORTAGE_LIMIT:
            beat_rows.append({"beat": row["beat"], "chars": row["chars"], "target": target, "shortage": round(ratio, 3)})
    return {
        "limit": DESIGN_SHORTAGE_LIMIT,
        "scene_target": scene_target,
        "scene_chars": scene_chars,
        "scene_shortage": round(scene_ratio, 3),
        "over_limit": scene_ratio >= DESIGN_SHORTAGE_LIMIT,
        "beats_over_limit": beat_rows,
    }


def assemble(title_line: str, pieces: list[tuple[str, str]]) -> str:
    body = "\n\n".join(f"<!--beat:{bid}-->\n{text}\n<!--/beat:{bid}-->" for bid, text in pieces)
    return title_line + "\n\n" + body + "\n"


def draft(
    work: Path,
    scene_id: str,
    run_id: str,
    *,
    candidates: int = 3,
    seed: int = 1,
    leaves: list[Path] | None = None,
    max_tokens: int = 4000,
    temperature: float = 0.7,
    timeout: float = 900,
    writer: Writer | None = None,
    relay: bool = False,
    log: Callable[[str], None] = print,
) -> Path:
    """relay=True のときは書き手を呼ばない。足りない候補があれば、その Beat のプロンプトを書いて
    RELAY_WAIT（終了コード3）で止まる。人が候補ファイルを置いてから同じ呼び出しをすれば、続きから進む。"""
    run, request, context = load_run(work, scene_id, run_id)
    profile, default_writer = resolve_writer(request, relay=relay) if writer is None else (None, writer)
    writer = writer or default_writer
    out_dir = run / OUT_DIR
    final = out_dir / "draft.md"
    if final.exists():
        raise BeatDraftError(f"作業稿が既にある（新しい run で prepare するか、{OUT_DIR}/ を退避する）: {final}")
    out_dir.mkdir(parents=True, exist_ok=True)

    materials = build_materials(work, scene_id, list(context.get("forbidden") or []), leaves or [])
    beats = list(context["beats"])
    first = first_beats(beats, materials.names)
    phrases = ps.trait_phrases(materials.character_md)
    appearance = ps.appearance_lines(materials.character_md)
    terms = ps.forbidden_terms(list(context.get("forbidden") or []))

    pieces: list[tuple[str, str]] = []
    introduced: set[str] = set()
    record: dict[str, Any] = {
        "schema": 1,
        "tool": "novel_beat_draft",
        "scene_id": scene_id,
        "run_id": run_id,
        "writer": {"model_id": (request.get("model") or {}).get("id"), "label": profile.label if profile else None},
        "params": {"candidates": candidates, "seed": seed, "max_tokens": max_tokens, "temperature": temperature,
                   "leaves": [str(p) for p in leaves or []], "relay": relay},
        "beats": [],
    }
    for i, beat in enumerate(beats):
        show = {n for n, at in first.items() if at == i}
        prior = materials.title_line + "\n\n" + "\n\n".join(t for _, t in pieces)
        # 書き手には床より上の指示目標（chars_instruction）を出す。短さの減点は床（chars_hint）で測る。
        hint = int(beat.get("chars_hint") or beat.get("chars_floor") or 500)
        target = int(beat.get("chars_instruction") or hint)
        prompt = beat_prompt(
            materials,
            show,
            prior,
            beat,
            target,
            i == 0,
            craft_notes=list(context.get("craft_notes") or []),
        )
        # 先取りの比べ先: 後の Beat の intent（設計の同じ項を分けた Beat でも、残りの出来事を先に書かせない）
        later = "".join(str(b.get("intent", "")) for b in beats[i + 1 :])
        current = str(beat["intent"])
        prompt_path = out_dir / f"beat{i + 1}.prompt.md"
        saved = [out_dir / f"beat{i + 1}.c{c + 1}.md" for c in range(candidates)]
        saved_prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else None
        if saved_prompt is not None and any(path.exists() for path in saved):
            if is_stale_saved_prompt(saved_prompt, prompt):
                # 中断のあとで資料（--leaf・設計・人物など）が変わった。古い候補と新しい候補を混ぜない
                raise BeatDraftError(
                    f"STALE_CANDIDATES: Beat {i + 1} の保存済みの候補は、今と違うプロンプトで書かれている"
                    f"（{prompt_path}）。新しい run で prepare するか、{OUT_DIR}/ の Beat {i + 1} 以降の候補を退避する",
                    code=1,
                )
            prompt = saved_prompt
        else:
            prompt_path.write_text(prompt, encoding="utf-8", newline="\n")
        if writer is None:
            waiting = [out_dir / f"beat{i + 1}.c{c + 1}.md" for c in range(candidates)
                       if not (out_dir / f"beat{i + 1}.c{c + 1}.md").exists()]
            if waiting:
                raise BeatDraftError(
                    f"RELAY_WAIT: Beat {i + 1}/{len(beats)} {beat['id']} の候補待ち。\n"
                    f"  プロンプト: {prompt_path}\n"
                    + "".join(f"  候補の置き場: {p}\n" for p in waiting)
                    + "  候補は1本ごとに新しい会話でプロンプトだけを渡して書かせ、返った本文だけを置く。置いたら同じコマンドを再実行する",
                    code=3,
                )
        rows = []
        for c in range(candidates):
            path = out_dir / f"beat{i + 1}.c{c + 1}.md"
            if path.exists():
                text = path.read_text(encoding="utf-8")
                reused = True
                finish = _saved_finish_reason(path)
            else:
                if writer is None:  # 中継の待ちは上で止めている
                    raise BeatDraftError(f"Beat {i + 1} の候補 {c + 1} が無い", code=1)
                try:
                    result = writer(prompt, model=profile.model if profile else None, max_tokens=max_tokens,
                                    temperature=temperature, seed=seed * 100 + i * 10 + c, timeout=timeout)
                except Exception as error:  # 書き手の誤りは保存済みの候補を残したまま止める
                    raise BeatDraftError(f"Beat {i + 1} の候補 {c + 1} で書き手が失敗: {error}", code=1) from error
                text = result.get("content") or ""
                if not text.strip():
                    raise BeatDraftError(f"Beat {i + 1} の候補 {c + 1} が空（finish_reason={result.get('finish_reason')}）", code=1)
                path.write_text(text + "\n", encoding="utf-8", newline="\n")
                meta = {k: v for k, v in result.items() if k not in ("content", "reasoning")}
                path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                reused = False
                finish = result.get("finish_reason")
            truncated = finish == "length"  # 生成打切り。削っても直らないので選ばない（GenerationTruncated と同じ扱い）
            body = clean(text)
            ov = ps.overlaps(body, prior) if pieces else []
            rd = ps.redescribed(body, introduced, appearance)
            la = ps.lookahead(body, later, current, prior) if later else []
            fb = ps.forbidden_hits(body, terms)
            rp = ps.repeated_lines(body, prior)
            rows.append({"candidate": path.name, "text": body, "reused": reused, "overlaps": ov, "redescribed": rd,
                         "lookahead": la, "forbidden": fb, "repeats": rp, "truncated": truncated,
                         "rejected": bool(truncated or ov or rd or la or fb or rp),
                         **score(body, hint, phrases)})
        if all(r["truncated"] for r in rows):
            raise BeatDraftError(
                f"GENERATION_TRUNCATED: Beat {i + 1}/{len(beats)} {beat['id']} の候補がすべて生成打切り"
                f"（finish_reason=length）。--max-tokens を上げ、この Beat の候補を退避してから再実行する", code=1)
        best, fallback = choose(rows)
        text, removed = best["text"], []
        if fallback:
            cut_text, removed = cut_copies(best["text"], prior if pieces else "", introduced, appearance,
                                           later=later, current=current, terms=terms)
            if cut_text.strip():
                text = cut_text
            else:  # 全部が写しだった。空の Beat にはせず、そのまま採って記録に残す
                removed = [dict(r, kept=True) for r in removed]
        pieces.append((str(beat["id"]), text))
        introduced |= {n for n in materials.names if n in str(beat["intent"])}
        chars = len(re.sub(r"\s", "", text))  # 空白（全角を含む）と改行を除いた字数
        record["beats"].append({
            "beat": beat["id"],
            "show_appearance": sorted(show),
            "selected": best["candidate"],
            "fallback": fallback,
            "cut": removed,
            "chars": chars,
            "chars_floor": hint,
            "candidates": [{k: v for k, v in r.items() if k != "text"} for r in rows],
        })
        ok = sum(1 for r in rows if not r["rejected"])
        cut_note = f"・写しの文を {sum(1 for r in removed if not r.get('kept'))} 削った" if fallback else ""
        log(f"Beat {i + 1}/{len(beats)} {beat['id']}: {best['candidate']} を採用（外れなし {ok}/{len(rows)}"
            f"{'・全落ち' if fallback else ''}{cut_note}）")
    final.write_text(assemble(materials.title_line, pieces), encoding="utf-8", newline="\n")
    record["draft_chars"] = len(ps.narration(final.read_text(encoding="utf-8")))
    record["fallback_beats"] = [b["beat"] for b in record["beats"] if b["fallback"]]
    # 床までの不足は言い換えで埋めない。加筆工程（出来事を足す。作者の承認）か Deepen へ回すための目安
    total = sum(b["chars"] for b in record["beats"])
    floor = int(context.get("chars_floor") or 0)
    record["shortfall"] = {
        "scene_chars": total,
        "scene_floor": floor,
        "scene_short": max(0, floor - total),
        "beats_short": [{"beat": b["beat"], "chars": b["chars"], "floor": b["chars_floor"]}
                        for b in record["beats"] if b["chars"] < b["chars_floor"]],
    }
    record["design_density"] = density_check(context, beats, record["beats"])
    (out_dir / "selection.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def plan(work: Path, scene_id: str, run_id: str, leaves: list[Path]) -> str:
    """書き手を呼ばずに、資料の量と、Beat ごとに外見を渡す人物を示す。"""
    run, request, context = load_run(work, scene_id, run_id)
    # 表示だけなので backend の接続は問わない（未接続の書き手も --relay の前に確かめられる）
    profile, _ = resolve_writer(request, relay=True)
    materials = build_materials(work, scene_id, list(context.get("forbidden") or []), leaves)
    beats = list(context["beats"])
    first = first_beats(beats, materials.names)
    lines = [
        f"run: {run}",
        f"書き手: {profile.model_id}（{profile.label}・{profile.tier}・{profile.backend}）",
        f"見出し: {materials.title_line}",
        f"資料（外見なし）: {len(materials.background(set()))} 字",
    ]
    for i, beat in enumerate(beats):
        show = sorted(n for n, at in first.items() if at == i)
        lines.append(f"  Beat {i + 1} {beat['id']}: 指示 {beat.get('chars_instruction') or beat.get('chars_hint')} 字"
                     f"（床 {beat.get('chars_hint')}）・外見を渡す人物 {show or 'なし'}")
    lines.append(f"床: {context.get('chars_floor')} 字（目安の合計 {sum(int(b.get('chars_hint') or 0) for b in beats)} 字）")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    try:
        from console_io import configure_stdio_utf8

        configure_stdio_utf8()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="低コンテキストの書き手で、Beat ごとに続きを書かせ、候補から選んで作業稿を組む")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("plan", "書き手を呼ばずに、資料の量と Beat ごとの外見の渡し方を示す"),
                       ("run", "候補を書かせ、選び、run の beat_draft/draft.md を組み立てる")):
        p = sub.add_parser(name, help=text)
        p.add_argument("work", type=Path, help="作品フォルダ（novels/<作品>）")
        p.add_argument("--scene-id", required=True)
        p.add_argument("--run-id", required=True)
        p.add_argument("--leaf", type=Path, action="append", default=[], help="起草で渡す葉（複数可）")
        if name == "run":
            p.add_argument("--candidates", type=int, default=3)
            p.add_argument("--seed", type=int, default=1)
            p.add_argument("--max-tokens", type=int, default=4000)
            p.add_argument("--temperature", type=float, default=0.7)
            p.add_argument("--timeout", type=float, default=900)
            p.add_argument("--relay", action="store_true",
                           help="書き手を呼ばない。足りない候補のプロンプトを書いて止まる（終了コード3）。"
                                "人がほかの道具で候補を置いたら、同じコマンドを再実行する")
    args = parser.parse_args(argv)
    work = args.work.resolve()
    if not work.is_dir():
        print(f"[ERROR] 作品フォルダが無い: {args.work}", file=sys.stderr)
        return 2
    try:
        if args.command == "plan":
            print(plan(work, args.scene_id, args.run_id, args.leaf))
            return 0
        if args.candidates < 1:
            raise BeatDraftError("--candidates は1以上")
        final = draft(work, args.scene_id, args.run_id, candidates=args.candidates, seed=args.seed, leaves=args.leaf,
                      max_tokens=args.max_tokens, temperature=args.temperature, timeout=args.timeout,
                      relay=args.relay)
    except BeatDraftError as error:
        if error.code == 3:  # 中継の候補待ちは誤りではない。次にすることを標準出力へ出す
            print(error)
        else:
            print(f"[ERROR] {error}", file=sys.stderr)
        return error.code
    selection = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))
    cut = sum(1 for b in selection["beats"] for r in b["cut"] if not r.get("kept"))
    short = selection["shortfall"]
    print(f"作業稿: {final}（本文 {short['scene_chars']} 字・全落ち {len(selection['fallback_beats'])} Beat・削った写しの文 {cut}）")
    print(f"選択の記録: {final.parent / 'selection.json'}")
    if short["scene_short"] or short["beats_short"]:
        beats = "、".join(f"{b['beat']} {b['chars']}/{b['floor']}" for b in short["beats_short"]) or "なし"
        print(f"床まで: 場面 {short['scene_chars']}/{short['scene_floor']} 字（不足 {short['scene_short']}）・床に届かない Beat: {beats}")
        print("  分量は清書で判定する（清書待ち）。言い換えで埋めない")
    density = selection["design_density"]
    if density["over_limit"] or density["beats_over_limit"]:
        beats = "、".join(f"{b['beat']} {b['chars']}/{b['target']}（{b['shortage']:.0%}）" for b in density["beats_over_limit"]) or "なし"
        print(f"DESIGN_DENSITY: 指示目標 {density['scene_target']} 字に対して場面は {density['scene_shortage']:.0%} 不足"
              f"（清書で判定）。{density['limit']:.0%} 以上足りない Beat: {beats}")
        print(f"  清書のあとも許容帯の外なら、子エピソードを足す案を作者へ出す（{SUB_EPISODE_LEAF}、{LENGTH_OPS} §4.7）")
    print("次: uv run python tools/writing_bridge_cli.py receive "
          f"{args.work.as_posix()} --scene-id {args.scene_id} --run-id {args.run_id} --candidate {final.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
