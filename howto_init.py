import json
import os
import re
import shutil
import sys
from pathlib import Path, PureWindowsPath


SKIP_NAMES = {"__pycache__", ".git", ".DS_Store"}
CATALOG_NAMES = {"_index.md", "README.md"}
MARKDOWN_LINK_TARGET = re.compile(r"\]\(([^)\s#]+)")


def relative_display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def copy_if_missing(src: Path, dst: Path, root: Path | None = None) -> None:
    display_root = root or Path.cwd()
    if not src.exists():
        print(f"  Skipping {src.name} (source not found)")
        return
    if dst.exists():
        print(f"  Skipping {relative_display(dst, display_root)} (already exists)")
        return
    print(
        f"  Copying {relative_display(src, display_root)} -> {relative_display(dst, display_root)}"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree_if_missing(src: Path, dst: Path, root: Path | None = None) -> None:
    if src.name in SKIP_NAMES:
        return
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in sorted(src.iterdir(), key=lambda item: item.name.lower()):
            copy_tree_if_missing(child, dst / child.name, root=root)
        return
    copy_if_missing(src, dst, root=root)


def catalog_link_targets(text: str) -> list[str]:
    targets: list[str] = []
    for target in MARKDOWN_LINK_TARGET.findall(text):
        if "://" in target or target in targets:
            continue
        targets.append(target)
    return targets


def find_stale_catalog_entries(src: Path, dst: Path) -> list[tuple[Path, list[str]]]:
    """Return working catalogs that lack link targets present in the standard catalog."""
    stale: list[tuple[Path, list[str]]] = []
    for standard in sorted(src.rglob("*"), key=lambda item: item.as_posix().lower()):
        if standard.name not in CATALOG_NAMES or not standard.is_file():
            continue
        if any(part in SKIP_NAMES for part in standard.relative_to(src).parts):
            continue
        working = dst / standard.relative_to(src)
        if not working.is_file():
            continue
        standard_text = standard.read_text(encoding="utf-8")
        working_text = working.read_text(encoding="utf-8")
        if standard_text == working_text:
            continue
        missing = [t for t in catalog_link_targets(standard_text) if t not in working_text]
        if missing:
            stale.append((working, missing))
    return stale


def report_stale_catalogs(src: Path, dst: Path, root: Path) -> None:
    stale = find_stale_catalog_entries(src, dst)
    if not stale:
        print("  Working catalogs list every standard entry.")
        return
    for working, missing in stale:
        print(f"  WARN {relative_display(working, root)} lacks {len(missing)} standard entries:")
        for target in missing:
            print(f"    - {target}")
    print("  These leaves are not selectable in Plan Mode until you add their lines to the working catalog.")
    print("  Copy the lines from the same file under _how_to.example/ (existing files are never overwritten).")


def interpreter_path_for_editor() -> str:
    if os.name == "nt":
        return "${workspaceFolder}/.venv/Scripts/python.exe"
    return "${workspaceFolder}/.venv/bin/python"


def merge_editor_python_settings(existing: dict, desired: dict) -> dict:
    merged = dict(existing)
    for key, value in desired.items():
        if key not in merged:
            merged[key] = value
    return merged


def write_editor_python_settings(root: Path) -> None:
    vscode_dir = root / ".vscode"
    settings_path = vscode_dir / "settings.json"
    desired = {
        "python.defaultInterpreterPath": interpreter_path_for_editor(),
        "python.terminal.activateEnvironment": True,
    }

    existing: dict = {}
    if settings_path.exists():
        try:
            loaded = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"  Skipping {relative_display(settings_path, root)} (invalid JSON: {exc})")
            return
        if not isinstance(loaded, dict):
            print(f"  Skipping {relative_display(settings_path, root)} (settings.json is not an object)")
            return
        existing = loaded

    merged = merge_editor_python_settings(existing, desired)
    if merged == existing and settings_path.exists():
        print(f"  Skipping {relative_display(settings_path, root)} (already exists)")
        return

    vscode_dir.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  Wrote {relative_display(settings_path, root)}")


def is_windows_store_stub(executable: Path) -> bool:
    # PureWindowsPath treats both "\\" and "/" as separators, so this also works on POSIX.
    return any(part.lower() == "windowsapps" for part in PureWindowsPath(str(executable)).parts)


def describe_python_runtime(root: Path) -> None:
    executable = Path(sys.executable)
    print(f"  interpreter: {executable}")
    if is_windows_store_stub(executable):
        print("  warning: Microsoft Store python stub detected. Use uv run python.")

    venv_python = root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    if venv_python.exists():
        print(f"  venv: {venv_python}")
    else:
        print("  warning: .venv is missing. Run uv sync first.")

    try:
        import pydantic
    except ImportError:
        print("  warning: pydantic is not importable. Run uv sync, then uv run python.")
    else:
        print(f"  pydantic: {pydantic.__version__}")


def howto_init(root: Path | None = None) -> int:
    root = (root or Path.cwd()).resolve()
    src = root / "_how_to.example"
    dst = root / "_how_to"

    if not src.exists():
        print(f"Error: Source directory '{src}' does not exist.")
        print("Run this from the repository root: uv run python howto_init.py")
        return 1

    if not dst.exists():
        print(f"Creating destination directory '{dst}'...")
        dst.mkdir(parents=True, exist_ok=True)

    print(f"Copying template files from '{src}' to '{dst}' (without overwriting existing files)...")
    copy_tree_if_missing(src, dst, root=root)

    print("\nChecking working catalogs against the standard catalogs...")
    report_stale_catalogs(src, dst, root)

    print("\nPreparing environment template files...")
    copy_if_missing(root / ".env.example", root / ".env", root=root)

    print("\nPreparing editor Python settings...")
    write_editor_python_settings(root)

    print("\nPython runtime:")
    describe_python_runtime(root)

    print("\nInitialization finished.")
    print("Use uv run python <script> for later tool commands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(howto_init())
