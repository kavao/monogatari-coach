"""ai_writer Phase 0 日本語 Benchmark の入口。実行: ``uv run python tools/ai_writer_bench_cli.py plan``。"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ai_writer.bench import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
