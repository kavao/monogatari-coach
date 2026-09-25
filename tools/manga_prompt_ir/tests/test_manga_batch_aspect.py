"""image_provider_novel_manga_batch の provider別縦横比解決。"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2]
_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from image_provider_novel_manga_batch import (  # noqa: E402
    MANGA_GROK_PRO_ASPECT_FALLBACK,
    MANGA_GROK_PRO_DEFAULT_ASPECT_ENV,
    main as manga_main,
    manga_grok_pro_effective_aspect_ratio,
    manga_page_effective_aspect_ratio,
)


def test_cli_overrides() -> None:
    assert manga_grok_pro_effective_aspect_ratio("9:16", "grok_pro", root=Path("/tmp")) == "9:16"


def test_openai_cli_aspect_is_forwarded() -> None:
    assert manga_grok_pro_effective_aspect_ratio("manga_b5_portrait", "openai", root=Path("/tmp")) == "manga_b5_portrait"


def test_non_grok_pro_returns_none() -> None:
    assert manga_grok_pro_effective_aspect_ratio(None, "novelai", root=Path("/tmp")) is None
    assert (
        manga_page_effective_aspect_ratio(
            None, "novelai", source="step1-panels", root=Path("/tmp")
        )
        is None
    )


def test_novelai_page_sources_do_not_fall_to_square() -> None:
    assert (
        manga_page_effective_aspect_ratio(
            None, "novelai", source="step1-pages", root=Path("/tmp")
        )
        == MANGA_GROK_PRO_ASPECT_FALLBACK
    )
    assert (
        manga_page_effective_aspect_ratio(
            None, "novelai", source="step2-pages", root=Path("/tmp")
        )
        == MANGA_GROK_PRO_ASPECT_FALLBACK
    )


def test_novelai_page_cli_aspect_overrides_default() -> None:
    assert (
        manga_page_effective_aspect_ratio(
            "story_vertical", "novelai", source="step1-pages", root=Path("/tmp")
        )
        == "story_vertical"
    )


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


def test_size_is_rejected_for_non_openai_provider(capsys) -> None:
    code = manga_main(
        [
            str(_ROOT / "tools" / "manga_prompt_ir" / "examples" / "p4_compare"),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "grok",
            "--size",
            "1024x1536",
            "--dry-run",
        ]
    )

    assert code == 2
    assert "--size は provider=openai" in capsys.readouterr().err
