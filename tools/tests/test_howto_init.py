from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import howto_init  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_howto_init_copies_nested_templates_without_overwrite(tmp_path: Path) -> None:
    example = tmp_path / "_how_to.example"
    _write(example / "novelcore.md", "example core\n")
    _write(example / "episode" / "general" / "episode_world.md", "example world\n")
    _write(example / ".env.example", "MONOCRI_ENV_VERSION=test\n")
    _write(tmp_path / ".env.example", "MONOCRI_ENV_VERSION=root\n")

    existing = tmp_path / "_how_to" / "novelcore.md"
    _write(existing, "user core\n")

    assert howto_init.howto_init(tmp_path) == 0

    assert (tmp_path / "_how_to" / "novelcore.md").read_text(encoding="utf-8") == "user core\n"
    copied = tmp_path / "_how_to" / "episode" / "general" / "episode_world.md"
    assert copied.read_text(encoding="utf-8") == "example world\n"
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "MONOCRI_ENV_VERSION=root\n"


def test_howto_init_writes_missing_editor_python_settings(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "_how_to.example" / "novelcore.md", "core\n")
    monkeypatch.setattr(howto_init, "interpreter_path_for_editor", lambda: "${workspaceFolder}/.venv/bin/python")

    assert howto_init.howto_init(tmp_path) == 0

    settings = json.loads((tmp_path / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.defaultInterpreterPath"] == "${workspaceFolder}/.venv/bin/python"
    assert settings["python.terminal.activateEnvironment"] is True


def test_howto_init_keeps_existing_interpreter_path(tmp_path: Path) -> None:
    _write(tmp_path / "_how_to.example" / "novelcore.md", "core\n")
    settings_path = tmp_path / ".vscode" / "settings.json"
    _write(
        settings_path,
        json.dumps({"python.defaultInterpreterPath": "C:/custom/python.exe", "editor.tabSize": 4})
        + "\n",
    )

    assert howto_init.howto_init(tmp_path) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["python.defaultInterpreterPath"] == "C:/custom/python.exe"
    assert settings["editor.tabSize"] == 4
    assert settings["python.terminal.activateEnvironment"] is True


def test_howto_init_returns_error_when_example_missing(tmp_path: Path) -> None:
    assert howto_init.howto_init(tmp_path) == 1


def test_windows_store_stub_detection() -> None:
    stub = Path(r"C:\Users\shiro\AppData\Local\Microsoft\WindowsApps\python.exe")
    venv = Path(r"C:\work\monogatari-coach\.venv\Scripts\python.exe")
    assert howto_init.is_windows_store_stub(stub) is True
    assert howto_init.is_windows_store_stub(venv) is False
