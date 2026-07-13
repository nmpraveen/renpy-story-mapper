from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog

from renpy_story_mapper.web import launcher
from renpy_story_mapper.web.api import ProjectApi
from renpy_story_mapper.web.picker import QtDialogAdapter

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "renpy_story_mapper"


class _SelectedPathDialogs:
    def __init__(self, selected: Path) -> None:
        self.selected = selected

    def choose_source(self, _kind: str) -> Path:
        return self.selected

    def choose_open_project(self) -> Path:
        return self.selected

    def choose_save_project(self) -> Path:
        return self.selected


def test_web_is_the_only_supported_product_entry_point() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = metadata["project"]["scripts"]

    assert scripts["renpy-story-mapper-web"] == "renpy_story_mapper.web.launcher:main"
    assert scripts["renpy-story-mapper"] == "renpy_story_mapper.cli:main"
    assert "renpy-story-mapper-gui" not in scripts
    assert all("renpy_story_mapper.ui" not in target for target in scripts.values())


def test_source_inventory_contains_no_legacy_desktop_product() -> None:
    assert not (PACKAGE / "ui").exists()
    owned_source = [
        path
        for path in PACKAGE.rglob("*.py")
        if "_vendor" not in path.parts
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in owned_source)

    assert "QGraphicsView" not in combined
    assert "renpy_story_mapper.ui" not in combined


def test_wheel_source_inventory_contains_browser_assets_and_no_legacy_ui() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = metadata["tool"]["hatch"]["build"]["targets"]["wheel"]
    static = PACKAGE / "web" / "static"
    manifest = json.loads((static / "asset-manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest["assets"])
    expected = {
        "API_CONTRACT.md",
        "api.js",
        "app.js",
        "contract.js",
        "graph.js",
        "index.html",
        "styles.css",
    }

    assert wheel["packages"] == ["src/renpy_story_mapper"]
    assert not (PACKAGE / "ui").exists()
    assert declared == expected
    assert all((static / name).is_file() for name in declared)


def test_picker_rejects_kind_confusion_before_native_dispatch() -> None:
    dialogs = QtDialogAdapter()

    with pytest.raises(ValueError, match="unsupported source picker kind"):
        dialogs.choose_source("project_save")
    with pytest.raises(ValueError, match="unsupported picker kind"):
        dialogs._choose("not-allow-listed")


def test_save_picker_enforces_project_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: ("C:/projects/story", ""),
    )
    dialogs = QtDialogAdapter()

    dialogs._choose("project_save")

    assert dialogs._result == Path("C:/projects/story.rsmproj")


def test_picker_response_uses_opaque_authority_and_does_not_leak_parent_path() -> None:
    selected = Path("C:/Users/private/secret/story.rpy")
    api = ProjectApi(_SelectedPathDialogs(selected))
    try:
        response = api.dispatch("POST", "/api/v1/native-picker", {"kind": "source"})
    finally:
        api.close()

    assert isinstance(response, dict)
    assert set(response) == {"selection_id", "kind", "display_name"}
    assert response["kind"] == "source"
    assert response["display_name"] == "story.rpy"
    assert "private" not in json.dumps(response).casefold()
    assert "secret" not in json.dumps(response).casefold()


def test_launcher_does_not_quit_when_native_picker_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: dict[str, object] = {}

    class _Signal:
        def connect(self, callback: object) -> None:
            events["shutdown_callback"] = callback

    class _Application:
        def __init__(self, _args: list[str]) -> None:
            self.aboutToQuit = _Signal()

        @staticmethod
        def instance() -> None:
            return None

        def setQuitOnLastWindowClosed(self, value: bool) -> None:
            events["quit_on_last_window"] = value

        def exec(self) -> int:
            return 0

    class _Server:
        port = 12345

        def close_service(self) -> None:
            events["server_closed"] = True

    class _Thread:
        def is_alive(self) -> bool:
            return False

        def join(self, *, timeout: int) -> None:
            events["join_timeout"] = timeout

    monkeypatch.setattr(launcher, "QApplication", _Application)
    monkeypatch.setattr(launcher, "QtDialogAdapter", object)
    monkeypatch.setattr(
        launcher,
        "QtShutdownBridge",
        lambda _app: SimpleNamespace(request=lambda: None),
    )
    monkeypatch.setattr(launcher, "ProjectApi", lambda _dialogs: object())
    monkeypatch.setattr(launcher, "LocalWebServer", lambda *_args, **_kwargs: _Server())
    monkeypatch.setattr(launcher, "start_in_thread", lambda _server: _Thread())

    assert launcher.main(["--no-browser"]) == 0
    assert events["quit_on_last_window"] is False
