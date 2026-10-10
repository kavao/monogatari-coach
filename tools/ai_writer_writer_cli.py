"""ai_writer Core Writer の確認の入口。実行: ``uv run python tools/ai_writer_writer_cli.py``（既定は dry-run）。"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ai_writer.writer_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
