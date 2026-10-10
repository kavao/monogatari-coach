"""ai_writer 字数不足への対処の比較の入口。実行: ``uv run python tools/ai_writer_length_cli.py plan``（既定は dry-run）。"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ai_writer.length_experiment import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
