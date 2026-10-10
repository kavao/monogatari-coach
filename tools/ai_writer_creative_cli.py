"""ai_writer 探索機能 E1「別の展開を見る」の入口。実行: ``uv run python tools/ai_writer_creative_cli.py plan --scene daily --model xialong-v1``。"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ai_writer.exploration import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
