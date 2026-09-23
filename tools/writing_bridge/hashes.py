"""raw / 正規化本文 / 範囲の SHA-256。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import unicodedata

from .errors import BridgeError


HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_BEAT_TOKEN = re.compile(r"<!--/?beat:[A-Za-z][A-Za-z0-9_-]*-->")
_FACT_TOKEN = re.compile(r"<!--fact:[A-Za-z][A-Za-z0-9_-]*-->")
_MARKUP_LINE = re.compile(
    r"^[ \t]*(?:<!--/?beat:[A-Za-z][A-Za-z0-9_-]*-->|<!--fact:[A-Za-z][A-Za-z0-9_-]*-->)[ \t]*\n?",
    re.MULTILINE,
)


def format_sha256(digest: bytes) -> str:
    return "sha256:" + digest.hex()


def raw_sha256(path: str | Path) -> str:
    return format_sha256(sha256(Path(path).read_bytes()).digest())


def normalize_body(text: str) -> str:
    """NFC、LF、Beat / fact マーカー除去。マーカーだけの行は行ごと落とす。"""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = unicodedata.normalize("NFC", cleaned)
    cleaned = _MARKUP_LINE.sub("", cleaned)
    cleaned = _BEAT_TOKEN.sub("", cleaned)
    cleaned = _FACT_TOKEN.sub("", cleaned)
    return cleaned


EMPTY_RAW_SHA256 = format_sha256(sha256(b"").digest())
EMPTY_TEXT_SHA256 = format_sha256(sha256(normalize_body("").encode("utf-8")).digest())


def text_sha256(text: str) -> str:
    return format_sha256(sha256(normalize_body(text).encode("utf-8")).digest())


def range_sha256(slice_text: str) -> str:
    return format_sha256(sha256(slice_text.encode("utf-8")).digest())


def read_normalized(path: str | Path) -> str:
    return normalize_body(Path(path).read_text(encoding="utf-8"))


def require_hash(value: str, *, field: str) -> str:
    if not HASH_RE.fullmatch(value):
        raise BridgeError(
            "BAD_HASH",
            f"{field} must be sha256: plus 64 lowercase hex digits",
            refs={"key": field, "value": value},
        )
    return value
