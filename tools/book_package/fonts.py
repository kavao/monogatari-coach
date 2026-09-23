"""Proof / cover font resolution for local publishing builds.

Supports multiple registered fonts (``font_ref``), TrueType (``.ttf``) and
TrueType Collection (``.ttc`` with ``subfontIndex``). Resolution failures are
reported per requested face so callers can surface actionable messages.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


class FontError(ValueError):
    """A requested font face cannot be resolved or registered."""


_FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}

# Family-name hints → common install locations (Windows first; expandable later).
_FAMILY_CANDIDATES: dict[str, tuple[Path, ...]] = {
    "BIZ UDPMincho": (
        Path(r"C:\Windows\Fonts\BIZ-UDMinchoM.ttc"),
        Path(r"C:\Windows\Fonts\BIZ-UDMincho-M.ttc"),
    ),
    "BIZ UDPGothic": (
        Path(r"C:\Windows\Fonts\BIZ-UDGothicR.ttc"),
        Path(r"C:\Windows\Fonts\BIZ-UDGothic-R.ttc"),
        Path(r"C:\Windows\Fonts\BIZ-UDGothicB.ttc"),
        Path(r"C:\Windows\Fonts\BIZ-UDGothic-B.ttc"),
    ),
    "Yu Mincho": (
        Path(r"C:\Windows\Fonts\yumin.ttf"),
        Path(r"C:\Windows\Fonts\yumindb.ttf"),
        Path(r"C:\Windows\Fonts\yuminl.ttf"),
    ),
    "Yu Gothic": (
        Path(r"C:\Windows\Fonts\YuGothR.ttc"),
        Path(r"C:\Windows\Fonts\YuGothM.ttc"),
        Path(r"C:\Windows\Fonts\YuGothB.ttc"),
    ),
    "Noto Serif JP": (
        Path(r"C:\Windows\Fonts\NotoSerifJP-VF.ttf"),
    ),
    "Noto Sans JP": (
        Path(r"C:\Windows\Fonts\NotoSansJP-VF.ttf"),
    ),
}

_DEFAULT_PROOF_CANDIDATES = (
    Path(r"C:\Windows\Fonts\yumin.ttf"),
    Path(r"C:\Windows\Fonts\NotoSerifJP-VF.ttf"),
    Path(r"C:\Windows\Fonts\BIZ-UDMinchoM.ttc"),
    Path(r"C:\Windows\Fonts\BIZ-UDMincho-M.ttc"),
)


@dataclass(frozen=True)
class ResolvedFont:
    """A font file that reportlab can embed for proof output."""

    path: Path
    subfont_index: int = 0
    family: str | None = None
    source: str = "candidate"


def _is_font_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _FONT_SUFFIXES


def _path_from_env(name: str) -> Path | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    return Path(raw).expanduser()


def resolve_font_path(
    *,
    file: str | Path | None = None,
    family: str | None = None,
    package_root: Path | None = None,
    env_var: str = "MONOCRI_BOOK_FONT",
) -> ResolvedFont:
    """Resolve one font face to an on-disk file.

    Resolution order:
    1. Explicit ``file`` (absolute, or package-relative when ``package_root`` is set)
    2. Environment variable ``env_var`` (default ``MONOCRI_BOOK_FONT``)
    3. Known candidates for ``family``
    4. Built-in Japanese proof candidates (when no family was requested)

    Raises:
        FontError: with a reason that names every failed candidate.
    """

    reasons: list[str] = []

    if file is not None:
        raw = Path(file).expanduser()
        candidates: list[Path] = []
        if raw.is_absolute():
            candidates.append(raw)
        elif package_root is not None:
            candidates.append((package_root / raw).resolve())
        else:
            candidates.append(raw)
        for candidate in candidates:
            if _is_font_file(candidate):
                return ResolvedFont(path=candidate, family=family, source="file")
            if candidate.exists():
                reasons.append(f"file は存在するが対応拡張子ではない: {candidate}")
            else:
                reasons.append(f"file が存在しない: {candidate}")

    env_path = _path_from_env(env_var)
    if env_path is not None:
        if _is_font_file(env_path):
            return ResolvedFont(path=env_path, family=family, source=env_var)
        if env_path.exists():
            reasons.append(
                f"{env_var} は存在するが .ttf/.otf/.ttc ではない: {env_path}"
            )
        else:
            reasons.append(f"{env_var} が指すファイルが存在しない: {env_path}")
    elif file is None and family is None:
        reasons.append(f"{env_var} が未設定")

    family_key = (family or "").strip()
    if family_key:
        matches = _FAMILY_CANDIDATES.get(family_key, ())
        if not matches:
            reasons.append(f"family の既知候補がありません: {family_key!r}")
        for candidate in matches:
            if _is_font_file(candidate):
                return ResolvedFont(
                    path=candidate, family=family_key, source="family_candidate"
                )
            reasons.append(f"family 候補が見つからない: {candidate}")

    if not family_key:
        for candidate in _DEFAULT_PROOF_CANDIDATES:
            if _is_font_file(candidate):
                return ResolvedFont(path=candidate, source="default_candidate")
            reasons.append(f"既定候補が見つからない: {candidate}")

    label = family_key or (str(file) if file else "default")
    detail = "; ".join(reasons) if reasons else "候補なし"
    raise FontError(f"書体 {label!r} を解決できません: {detail}")


def register_font(
    face_name: str,
    resolved: ResolvedFont,
    *,
    subfont_index: int | None = None,
) -> str:
    """Register ``resolved`` under ``face_name`` for reportlab and return the name."""

    index = resolved.subfont_index if subfont_index is None else subfont_index
    if face_name not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(
                TTFont(face_name, str(resolved.path), subfontIndex=index)
            )
        except (OSError, ValueError) as exc:
            raise FontError(
                f"書体 {face_name!r} を登録できません "
                f"({resolved.path}, subfontIndex={index}): {exc}"
            ) from exc
    return face_name


def register_named_fonts(
    specs: dict[str, dict[str, object]],
    *,
    package_root: Path | None = None,
) -> dict[str, ResolvedFont]:
    """Resolve and register a mapping of ``font_ref`` → {family, file, subfont_index}.

    Returns the resolved faces keyed by ``font_ref``. Failures raise ``FontError``
    with the failing ``font_ref`` named first.
    """

    registered: dict[str, ResolvedFont] = {}
    for font_ref, spec in specs.items():
        family = spec.get("family")
        file = spec.get("file")
        index_raw = spec.get("subfont_index", 0)
        try:
            if index_raw is None:
                index = 0
            elif isinstance(index_raw, (str, int, float)):
                index = int(index_raw)
            else:
                raise TypeError("整数、浮動小数、または文字列で指定してください")
        except (TypeError, ValueError) as exc:
            raise FontError(
                f"font_ref {font_ref!r} の subfont_index が整数ではありません: {index_raw!r}"
            ) from exc
        try:
            resolved = resolve_font_path(
                file=str(file) if file else None,
                family=str(family) if family else None,
                package_root=package_root,
            )
            if index:
                resolved = ResolvedFont(
                    path=resolved.path,
                    subfont_index=index,
                    family=resolved.family,
                    source=resolved.source,
                )
            register_font(f"MonocriCover_{font_ref}", resolved)
        except FontError as exc:
            raise FontError(f"font_ref {font_ref!r}: {exc}") from exc
        registered[font_ref] = resolved
    return registered


def find_proof_font() -> Path:
    """Return a local Japanese font usable for body proof text (backward compatible)."""

    resolved = resolve_font_path()
    return resolved.path


def register_proof_font(face_name: str = "MonocriProofMincho") -> tuple[str, Path]:
    """Register the default body proof font and return ``(face_name, path)``."""

    resolved = resolve_font_path()
    register_font(face_name, resolved)
    return face_name, resolved.path
