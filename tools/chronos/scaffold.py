"""CHRONOS 作品フォルダの雛形生成。既存ファイルは上書きしない。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .models import (
    CharacterFile,
    ChronosConfig,
    EventFile,
    LocationFile,
    SceneFile,
)
from .storage import atomic_write_model, atomic_write_text


class ChronosInitError(FileExistsError):
    """既にある chronos ルートを壊さない。"""


_README = """# CHRONOS

このフォルダは物語内部時間の正本です。日付は省略できます。順序は `time.after` / `time.before` で書きます。

- `events/` は章単位 YAML に複数イベントを収容します。未配置は `unplaced.yaml` です。
- `check` は決定的 lint です。LLM は呼びません。
- `world.md` や `_novel_text` は検査の副作用では書き換えません。
- `.cache/` は導出物です。P1 以降で使います。削除しても再計算できます。
"""


def planned_paths(chronos_root: Path) -> list[Path]:
    return [
        chronos_root / "README.md",
        chronos_root / "chronos.config.yaml",
        chronos_root / "entities" / "characters.yaml",
        chronos_root / "entities" / "locations.yaml",
        chronos_root / "scenes.yaml",
        chronos_root / "events" / "unplaced.yaml",
        chronos_root / ".cache" / ".gitignore",
    ]


def resolve_init_root(novel_root: str | Path) -> Path:
    root = Path(novel_root)
    if root.name == "chronos":
        return root
    return root / "chronos"


def init_chronos(
    novel_root: str | Path,
    *,
    exist_ok: bool = False,
    dry_run: bool = False,
) -> Path:
    chronos_root = resolve_init_root(novel_root)
    if chronos_root.exists() and not exist_ok:
        if any(chronos_root.iterdir()):
            raise ChronosInitError(f"chronos already exists: {chronos_root}")
    if dry_run:
        return chronos_root
    chronos_root.mkdir(parents=True, exist_ok=True)
    (chronos_root / "events").mkdir(exist_ok=True)
    (chronos_root / "entities").mkdir(exist_ok=True)
    (chronos_root / ".cache").mkdir(exist_ok=True)

    _new_text(chronos_root / "README.md", _README)
    _new_model(chronos_root / "chronos.config.yaml", ChronosConfig())
    _new_model(chronos_root / "entities" / "characters.yaml", CharacterFile())
    _new_model(chronos_root / "entities" / "locations.yaml", LocationFile())
    _new_model(chronos_root / "scenes.yaml", SceneFile())
    _new_model(chronos_root / "events" / "unplaced.yaml", EventFile())
    gitignore = chronos_root / ".cache" / ".gitignore"
    if not gitignore.exists():
        atomic_write_text(gitignore, "*\n!.gitignore\n")
    return chronos_root


def _new_text(path: Path, text: str) -> None:
    if path.exists():
        return
    atomic_write_text(path, text)


def _new_model(path: Path, model: BaseModel) -> None:
    if path.exists():
        return
    atomic_write_model(path, model)
