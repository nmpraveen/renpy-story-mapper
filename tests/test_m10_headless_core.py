from __future__ import annotations

import os
import subprocess
import sys


def test_deterministic_core_and_organization_contracts_import_without_qt() -> None:
    script = r"""
import builtins

original_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name.startswith("PySide6"):
        raise ModuleNotFoundError("PySide6 deliberately unavailable")
    return original_import(name, *args, **kwargs)

builtins.__import__ = blocked_import

for module in (
    "renpy_story_mapper.parser",
    "renpy_story_mapper.graph",
    "renpy_story_mapper.control_flow",
    "renpy_story_mapper.route_map",
    "renpy_story_mapper.project_analysis",
    "renpy_story_mapper.organization.contracts",
    "renpy_story_mapper.organization.cache",
):
    __import__(module)
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in sys.path if isinstance(item, str)
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
