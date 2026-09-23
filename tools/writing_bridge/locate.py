"""C1 座標の下書き。意味判定はしない。"""

from __future__ import annotations

from pathlib import Path
import unicodedata

from pydantic import Field, field_validator

from .commands import (
    _assert_base_text_current,
    _assert_received_candidates_current,
    _resolve_inspect_edition,
    run_dir,
    work_root_of,
)
from .errors import BridgeError
from .hashes import range_sha256
from .models import HASH, SCHEMA, RequestDocument, StrictModel
from .storage import load_model


class QuoteLocateDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    range_sha256: str = Field(pattern=HASH)
    text_sha256: str = Field(pattern=HASH)

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value

    @classmethod
    def from_span(cls, *, quote: str, start: int, end: int, text_sha: str) -> "QuoteLocateDocument":
        return cls(
            schema=SCHEMA,
            quote=quote,
            start=start,
            end=end,
            range_sha256=range_sha256(quote),
            text_sha256=text_sha,
        )


def normalize_quote(quote: str) -> str:
    cleaned = quote.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", cleaned)


def locate_quote(normalized: str, quote: str, *, text_sha256: str) -> QuoteLocateDocument:
    needle = normalize_quote(quote)
    if not needle:
        raise BridgeError("MISSING_FIELD", "quote is required")
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        index = normalized.find(needle, start)
        if index < 0:
            break
        spans.append((index, index + len(needle)))
        start = index + 1
    if not spans:
        raise BridgeError("UNKNOWN_REF", "quote was not found", refs={"quote": needle})
    if len(spans) > 1:
        raise BridgeError(
            "JOB_CONFLICT",
            "quote is not unique; do not guess",
            refs={"quote": needle, "count": len(spans)},
        )
    left, right = spans[0]
    return QuoteLocateDocument.from_span(
        quote=needle,
        start=left,
        end=right,
        text_sha=text_sha256,
    )


def locate_quote_run(
    work_root: Path,
    *,
    scene_id: str,
    run_id: str,
    quote: str,
    marked_path: Path | None = None,
) -> tuple[int, str]:
    root = work_root_of(work_root)
    dest = run_dir(root, scene_id, run_id)
    if not dest.is_dir():
        raise BridgeError("UNKNOWN_REF", f"run not found: {dest}")
    request = load_model(dest / "request.yaml", RequestDocument)
    _assert_base_text_current(root, request)
    _assert_received_candidates_current(root, dest)
    _path, normalized, text_sha = _resolve_inspect_edition(root, request, dest, marked_path)
    located = locate_quote(normalized, quote, text_sha256=text_sha)
    return 0, located.model_dump_json(by_alias=True, indent=2) + "\n"
