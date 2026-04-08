"""
後方互換用ラッパー。実体は rulesync CLI のフル生成と同じ。

推奨: プロジェクトルートで直接

    rulesync generate

を実行する（引数なしで全ターゲット・全機能を再生成）。

注意: `uv run python sync_rules.py` を使う場合も、シェル経由で PATH を解決するため
npm グローバルの rulesync が通常のターミナルと同様に見えます（Windows の .cmd シムも含む）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    # shell=True: Windows で rulesync.cmd を確実に起動し、ユーザーの PATH を引き継ぐ
    return subprocess.run(
        "rulesync generate -V",
        cwd=repo_root,
        shell=True,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
