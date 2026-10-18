"""試し書き・書き比べの入口。実行: ``uv run python tools/ai_writer_compare_cli.py plan novels/NNN_作品名 --scene-id ch01-001``。

正本（``_novel_text/``）・``_writing/``・``_metron/`` には書かない。NovelAI への送信は ``run --execute`` だけ。
"""

from __future__ import annotations

import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ai_writer.compare import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
