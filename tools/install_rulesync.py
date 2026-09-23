"""Download and verify the fixed Rulesync binary for this repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "rulesync_toolchain.json"


def load_config() -> dict[str, str]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_version(binary: Path, expected: str) -> None:
    result = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=False
    )
    actual = result.stdout.strip()
    if result.returncode or actual != expected:
        raise RuntimeError(
            f"Rulesync version verification failed: expected {expected}, got {actual or result.stderr.strip()!r}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="download again even when the cached binary is valid")
    args = parser.parse_args()
    config = load_config()
    binary = ROOT / config["cache_path"]
    expected_hash = config["sha256"].lower()

    if binary.is_file() and not args.force:
        if sha256(binary) == expected_hash:
            verify_version(binary, config["version"])
            print(f"Rulesync {config['version']} is ready: {binary}")
            return 0
        print("Cached Rulesync binary has an unexpected SHA-256; downloading a verified replacement.")

    binary.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix="rulesync-", suffix=".download", dir=binary.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        print(f"Downloading Rulesync {config['version']} ({config['platform']})...")
        with urllib.request.urlopen(config["url"]) as response, temporary.open("wb") as handle:
            while block := response.read(1024 * 1024):
                handle.write(block)
        actual_hash = sha256(temporary)
        if actual_hash != expected_hash:
            raise RuntimeError(f"SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
        os.replace(temporary, binary)
        verify_version(binary, config["version"])
        print(f"Rulesync {config['version']} installed and verified: {binary}")
        return 0
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
