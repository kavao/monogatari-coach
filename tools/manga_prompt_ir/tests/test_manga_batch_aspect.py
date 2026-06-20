"""image_provider_novel_manga_batch の grok_pro 縦横比解決。"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from image_provider_novel_manga_batch import (  # noqa: E402
    MANGA_GROK_PRO_ASPECT_FALLBACK,
    MANGA_GROK_PRO_DEFAULT_ASPECT_ENV,
    manga_grok_pro_effective_aspect_ratio,
)


def test_cli_overrides() -> None:
    assert manga_grok_pro_effective_aspect_ratio("9:16", "grok_pro", root=Path("/tmp")) == "9:16"


def test_non_grok_pro_returns_none() -> None:
    assert manga_grok_pro_effective_aspect_ratio(None, "novelai", root=Path("/tmp")) is None


def test_fallback_when_no_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(MANGA_GROK_PRO_DEFAULT_ASPECT_ENV, raising=False)
    assert (
        manga_grok_pro_effective_aspect_ratio(None, "grok_pro", root=tmp_path)
        == MANGA_GROK_PRO_ASPECT_FALLBACK
    )


def test_reads_dotenv_without_os_environ(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(MANGA_GROK_PRO_DEFAULT_ASPECT_ENV, raising=False)
    (tmp_path / ".env").write_text(
        f"{MANGA_GROK_PRO_DEFAULT_ASPECT_ENV}=portrait\n",
        encoding="utf-8",
    )
    assert manga_grok_pro_effective_aspect_ratio(None, "grok_pro", root=tmp_path) == "portrait"
