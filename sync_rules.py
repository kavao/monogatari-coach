"""
後方互換用ラッパー。実体は固定・検証済み Rulesync 15.0.1 のフル生成と同じ。

初回は `python tools/install_rulesync.py` で単体バイナリを取得する。
日常の生成は `python tools/rulesync.py generate` または本ラッパーを使う。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    return subprocess.run(
        [sys.executable, str(repo_root / "tools" / "rulesync.py"), "generate"],
        cwd=repo_root,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
