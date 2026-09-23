"""CHRONOS の正規入口。実行: ``python tools/chronos_cli.py``。"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from chronos.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
