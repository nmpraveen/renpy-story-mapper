"""Atomic per-user state for browser preferences and recent local projects."""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from renpy_story_mapper.web.contracts import JsonValue, json_value

DEFAULT_SETTINGS: dict[str, JsonValue] = {
    "theme": "system",
    "zoom": 1,
    "include_technical": False,
    "include_unresolved": True,
    "show_requirements": True,
    "show_effects": True,
}


class UserStateStore:
    """Store only local UI state; paths are never returned directly by this class's callers."""

    def __init__(self, path: Path | None = None) -> None:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self.path = path or local / "RenPyStoryMapper" / "web-state.json"
        self._lock = threading.Lock()

    def settings(self) -> dict[str, JsonValue]:
        with self._lock:
            data = self._read()
        raw = data.get("settings")
        result = dict(DEFAULT_SETTINGS)
        if isinstance(raw, dict):
            result.update({key: value for key, value in raw.items() if key in result})
        return result

    def save_settings(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if any(key not in DEFAULT_SETTINGS for key in values):
            raise ValueError("unknown browser setting")
        current = self.settings()
        current.update(values)
        self._validate_settings(current)
        with self._lock:
            data = self._read()
            data["settings"] = current
            self._write(data)
        return current

    def recent_projects(self) -> tuple[Path, ...]:
        with self._lock:
            raw = self._read().get("recent_projects")
        if not isinstance(raw, list):
            return ()
        result: list[Path] = []
        for value in raw[:12]:
            if isinstance(value, str):
                path = Path(value)
                if path.suffix.lower() == ".rsmproj" and path.is_file():
                    result.append(path.resolve())
        return tuple(result)

    def record_project(self, path: Path) -> None:
        resolved = path.resolve()
        with self._lock:
            data = self._read()
            raw = data.get("recent_projects")
            existing = (
                [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
            )
            target = os.path.normcase(str(resolved))
            values = [str(resolved)] + [
                item for item in existing if os.path.normcase(item) != target
            ]
            data["recent_projects"] = json_value(values[:12])
            self._write(data)

    def _read(self) -> dict[str, JsonValue]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write(self, data: dict[str, JsonValue]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
            )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _validate_settings(settings: dict[str, JsonValue]) -> None:
        if settings["theme"] not in {"system", "light", "dark"}:
            raise ValueError("invalid theme")
        zoom = settings["zoom"]
        if not isinstance(zoom, (int, float)) or isinstance(zoom, bool) or not 0.5 <= zoom <= 2:
            raise ValueError("invalid zoom")
        for name in (
            "include_technical",
            "include_unresolved",
            "show_requirements",
            "show_effects",
        ):
            if not isinstance(settings[name], bool):
                raise ValueError(f"invalid {name}")
