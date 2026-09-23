"""Extract structural HTML-comment references from publication Markdown."""

from __future__ import annotations

from dataclasses import dataclass
import re


_SCENE_PATTERN = re.compile(
    r"<!--\s*scene:\s*(?P<chapter>ch\d{2,})-(?P<sequence>\d{3,})\s*-->"
)
_ILLUSTRATION_PATTERN = re.compile(
    r"<!--\s*illustration:\s*(?P<identifier>[a-z][a-z0-9_]*)\s*-->"
)


@dataclass(frozen=True)
class SceneAnchor:
    id: str
    chapter_id: str
    sequence: int


@dataclass(frozen=True)
class IllustrationDirective:
    illustration_id: str


def extract_scene_anchors(text: str) -> list[SceneAnchor]:
    return [
        SceneAnchor(
            id=f"{match.group('chapter')}-{match.group('sequence')}",
            chapter_id=match.group("chapter"),
            sequence=int(match.group("sequence")),
        )
        for match in _SCENE_PATTERN.finditer(text)
    ]


def extract_illustration_directives(text: str) -> list[IllustrationDirective]:
    return [
        IllustrationDirective(illustration_id=match.group("identifier"))
        for match in _ILLUSTRATION_PATTERN.finditer(text)
    ]
