from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate.ps1"
POWERSHELL = shutil.which("powershell")


def _dry_run(*arguments: str) -> subprocess.CompletedProcess[str]:
    if POWERSHELL is None:
        pytest.skip("Windows PowerShell is required for validate.ps1 coverage")
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
            "-DryRun",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_fast_dry_run_is_bounded_and_deterministic() -> None:
    result = _dry_run("-Tier", "Fast")

    assert result.returncode == 0, result.stderr
    assert "Python version (30s)" in result.stdout
    assert "Ruff (120s)" in result.stdout
    assert "Fast deterministic pytest (180s)" in result.stdout
    assert "Full pytest" not in result.stdout
    assert "browser acceptance" not in result.stdout.casefold()


def test_focused_dry_run_passes_exact_pytest_target() -> None:
    target = "tests/test_parser_graph.py::test_linear_fallthrough"
    result = _dry_run("-Tier", "Focused", "-PytestTarget", target)

    assert result.returncode == 0, result.stderr
    assert "Focused pytest (600s)" in result.stdout
    assert target in result.stdout
    assert "Full pytest" not in result.stdout


def test_release_dry_run_discovers_static_build_and_safe_acceptance() -> None:
    result = _dry_run("-Tier", "Release")

    assert result.returncode == 0, result.stderr
    assert "Full deterministic pytest (900s)" in result.stdout
    assert "not hardware_sensitive" in result.stdout
    assert "JavaScript syntax:" in result.stdout
    assert "Build isolated sdist and wheel (300s)" in result.stdout
    assert "--sdist --wheel" in result.stdout
    assert "Install built wheel into isolated target (180s)" in result.stdout
    assert "hardware-sensitive acceptance" not in result.stdout
    assert "private acceptance" not in result.stdout.casefold()
    assert "Opt-in browser acceptance" not in result.stdout


def test_release_browser_acceptance_requires_explicit_switch() -> None:
    result = _dry_run("-Tier", "Release", "-IncludeBrowser")

    assert result.returncode == 0, result.stderr
    assert "Opt-in browser acceptance:" in result.stdout
    assert "m11_browser_acceptance.py" in result.stdout


def test_release_hardware_sensitive_acceptance_requires_explicit_switch() -> None:
    result = _dry_run("-Tier", "Release", "-IncludeHardwareSensitive")

    assert result.returncode == 0, result.stderr
    assert "not hardware_sensitive" not in result.stdout
    assert "Opt-in hardware-sensitive acceptance:" in result.stdout
    assert "m11_scale_acceptance.py" in result.stdout


def test_release_private_acceptance_requires_explicit_script() -> None:
    script = ROOT / "scripts" / "m11_private_acceptance.py"
    result = _dry_run(
        "-Tier",
        "Release",
        "-IncludePrivate",
        "-PrivateScript",
        str(script),
        "-PrivateArgument",
        "--help",
    )

    assert result.returncode == 0, result.stderr
    assert "Opt-in private acceptance: m11_private_acceptance.py" in result.stdout
    assert "--help" in result.stdout
