"""Run the repository's verified, fixed-version Rulesync binary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "rulesync_toolchain.json"
AGENTSMD_COMPATIBILITY_NOTICES = frozenset(
    {
        "Target 'agentsmd' only supports simulated 'skills'. Use '--simulate-skills' to enable it. Skipping.",
        "Target 'agentsmd' only supports simulated 'subagents'. Use '--simulate-subagents' to enable it. Skipping.",
        "Target 'agentsmd' does not support the feature 'mcp'. Skipping.",
    }
)


def is_expected_agentsmd_notice(line: str) -> bool:
    """Return whether a line is an intentional agentsmd compatibility notice."""
    return line.rstrip("\r\n") in AGENTSMD_COMPATIBILITY_NOTICES


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    binary = ROOT / config["cache_path"]
    if not binary.is_file():
        print("Rulesync is not installed. Run: python tools/install_rulesync.py", file=sys.stderr)
        return 2
    process = subprocess.Popen(
        [str(binary), *sys.argv[1:]],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for line in process.stdout:
        decoded_line = line.decode("utf-8", errors="replace")
        if not is_expected_agentsmd_notice(decoded_line):
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
    return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
