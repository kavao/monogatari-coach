# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOLS_ROOT))

from image_provider_novel_manga_batch import (  # noqa: E402
    MANGA_NOVELAI_REFERENCE_PATHS_ENV,
    resolve_novelai_reference,
)


def test_resolve_novelai_reference_none_skips_env(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    root = tmp_path / "repo"
    cross = root / "_how_to" / "image_refs" / "novelai"
    cross.mkdir(parents=True)
    bundle = cross / "flat.naiv4vibebundle"
    bundle.write_bytes(b"x")

    (novel / "_meta.yaml").write_text(
        """
version: 1
novelai:
  portion_default: "none"
  portion_fallback: "none"
  portions:
    cross_flat:
      path: _how_to/image_refs/novelai/flat.naiv4vibebundle
""".strip(),
        encoding="utf-8",
    )
    (root / ".env").write_text(
        f"{MANGA_NOVELAI_REFERENCE_PATHS_ENV}={bundle.as_posix()}\n",
        encoding="utf-8",
    )

    got = resolve_novelai_reference([], root, novel_dir=novel)
    assert got.paths == []
    assert got.source == "_meta.yaml#none"
