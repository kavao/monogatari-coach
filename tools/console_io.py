"""Shared console helpers for CLI tools."""

from __future__ import annotations

import sys


def configure_stdio_utf8() -> None:
    """Reconfigure stdout/stderr to UTF-8 when the runtime supports it."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass