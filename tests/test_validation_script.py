from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path
from typing import IO

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate.ps1"
PR_WORKFLOW = ROOT / ".github" / "workflows" / "pull-request-checks.yml"
POWERSHELL = shutil.which("powershell")


def test_sdist_excludes_local_acceptance_trees() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    exclusions = configuration["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"]

    assert "/output" in exclusions
    assert "/docs/handoffs" in exclusions


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


def _powershell_command(*arguments: str) -> list[str]:
    assert POWERSHELL is not None
    return [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        *arguments,
    ]


def _pid_is_running(pid: int) -> bool:
    tasklist = subprocess.run(
        ["tasklist.exe", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    return any(
        len(row) >= 2 and row[1] == str(pid)
        for row in csv.reader(tasklist.stdout.splitlines())
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


def test_release_no_timeout_disables_every_process_cutoff() -> None:
    result = _dry_run("-Tier", "Release", "-NoTimeout")

    assert result.returncode == 0, result.stderr
    assert "Python version (no timeout)" in result.stdout
    assert "Full deterministic pytest (no timeout)" in result.stdout
    assert "Ruff (no timeout)" in result.stdout
    assert "Build isolated sdist and wheel (no timeout)" in result.stdout
    assert "Install built wheel into isolated target (no timeout)" in result.stdout


def test_pull_request_release_components_have_no_repository_timeout() -> None:
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "timeout-minutes:" not in workflow
    assert "validate.ps1 -Tier Release -ReleaseComponent Quality -NoTimeout" in workflow
    assert "validate.ps1 -Tier Release -ReleaseComponent Package -NoTimeout" in workflow


def test_release_quality_component_excludes_pytest_and_package() -> None:
    result = _dry_run("-Tier", "Release", "-ReleaseComponent", "Quality", "-NoTimeout")

    assert result.returncode == 0, result.stderr
    assert "Ruff (no timeout)" in result.stdout
    assert "Strict mypy (no timeout)" in result.stdout
    assert "Full deterministic pytest" not in result.stdout
    assert "Build isolated sdist and wheel" not in result.stdout


def test_release_package_component_excludes_pytest_and_quality() -> None:
    result = _dry_run("-Tier", "Release", "-ReleaseComponent", "Package", "-NoTimeout")

    assert result.returncode == 0, result.stderr
    assert "Build isolated sdist and wheel (no timeout)" in result.stdout
    assert "Install built wheel into isolated target (no timeout)" in result.stdout
    assert "Full deterministic pytest" not in result.stdout
    assert "Ruff" not in result.stdout
    assert "Strict mypy" not in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ("-IncludeBrowser",),
        ("-IncludeHardwareSensitive",),
        (
            "-IncludePrivate",
            "-PrivateScript",
            str(ROOT / "scripts" / "m11_private_acceptance.py"),
        ),
    ],
)
def test_release_component_rejects_opt_in_acceptance(arguments: tuple[str, ...]) -> None:
    result = _dry_run("-Tier", "Release", "-ReleaseComponent", "Quality", *arguments)

    assert result.returncode != 0
    assert "Opt-in acceptance requires -ReleaseComponent All" in result.stderr


def test_real_validation_streams_and_timeout_kills_descendant_tree() -> None:
    if POWERSHELL is None or sys.platform != "win32":
        pytest.skip("Windows PowerShell process-tree behavior is required")
    probe_root = Path(tempfile.mkdtemp(prefix="renpy-validation-probe-"))
    pid_path = probe_root / "descendant.pid"
    probe = probe_root / "test_stream_probe.py"
    probe.write_text(
        "\n".join(
            (
                "import pathlib",
                "import subprocess",
                "import sys",
                "import time",
                "",
                "def test_stream_and_tree():",
                "    child = subprocess.Popen([",
                "        sys.executable, '-u', '-c',",
                "        \"import time; print('DESCENDANT_READY', flush=True); time.sleep(60)\"",
                "    ])",
                f"    pathlib.Path({str(pid_path)!r}).write_text(str(child.pid))",
                "    print('STREAM_STDOUT_READY', flush=True)",
                "    print('STREAM_STDERR_READY', file=sys.stderr, flush=True)",
                "    time.sleep(60)",
            )
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    nested_pytest_temp = probe_root / "nested-pytest-temp"
    environment["PYTEST_ADDOPTS"] = (
        f'-s --rootdir="{probe_root.as_posix()}" '
        f'--confcutdir="{probe_root.as_posix()}" '
        f'--basetemp="{nested_pytest_temp.as_posix()}"'
    )
    process = subprocess.Popen(
        _powershell_command(
            "-Tier",
            "Focused",
            "-PytestTarget",
            str(probe),
            "-TimeoutSeconds",
            "20",
        ),
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    assert process.stderr is not None
    lines: list[str] = []
    required_markers = {"STREAM_STDOUT_READY", "STREAM_STDERR_READY"}
    observed_markers: set[str] = set()
    marker_arrived_live: dict[str, bool] = {}
    readiness = threading.Event()
    capture_lock = threading.Lock()

    def drain(stream: IO[str]) -> None:
        for line in stream:
            with capture_lock:
                lines.append(line)
                for marker in required_markers:
                    if marker in line:
                        observed_markers.add(marker)
                        marker_arrived_live[marker] = process.poll() is None
                if observed_markers == required_markers:
                    readiness.set()

    readers = [
        threading.Thread(target=drain, args=(stream,), daemon=True)
        for stream in (process.stdout, process.stderr)
    ]
    for reader in readers:
        reader.start()

    descendant_pid: int | None = None
    tree_was_terminated = False
    try:
        readiness_deadline = time.monotonic() + 60
        while not readiness.wait(timeout=0.1):
            if process.poll() is not None and not any(
                reader.is_alive() for reader in readers
            ):
                break
            if time.monotonic() >= readiness_deadline:
                break
        with capture_lock:
            readiness_output = "".join(lines)
        assert readiness.is_set(), (
            "validation never streamed probe readiness:\n" + readiness_output
        )
        assert all(marker_arrived_live.values())
        assert process.poll() is None, "readiness was buffered until validation exited"
        assert "Validation summary" not in readiness_output
        assert pid_path.is_file()
        pid_text = pid_path.read_text(encoding="utf-8").strip()
        assert pid_text.isdecimal()
        descendant_pid = int(pid_text)

        process.wait(timeout=30)
        for reader in readers:
            reader.join(timeout=5)

        with capture_lock:
            combined = "".join(lines)
        assert process.returncode == 1
        assert combined.index("STREAM_STDOUT_READY") < combined.index(
            "Validation summary"
        )
        assert combined.index("STREAM_STDERR_READY") < combined.index(
            "Validation summary"
        )
        assert "timed out" in combined
        assert "124" in combined

        death_deadline = time.monotonic() + 10
        while time.monotonic() < death_deadline:
            if not _pid_is_running(descendant_pid):
                tree_was_terminated = True
                break
            time.sleep(0.1)
        assert tree_was_terminated, "validation left the descendant process running"
    finally:
        if process.poll() is None:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            process.wait(timeout=10)
        for reader in readers:
            reader.join(timeout=10)
        if descendant_pid is None and pid_path.is_file():
            pid_text = pid_path.read_text(encoding="utf-8").strip()
            if pid_text.isdecimal():
                descendant_pid = int(pid_text)
        if descendant_pid is not None and not tree_was_terminated:
            subprocess.run(
                ["taskkill.exe", "/PID", str(descendant_pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        shutil.rmtree(probe_root)


def test_release_browser_acceptance_requires_explicit_switch() -> None:
    result = _dry_run("-Tier", "Release", "-IncludeBrowser")

    assert result.returncode == 0, result.stderr
    assert "Opt-in browser acceptance:" in result.stdout
    assert "m13_browser_acceptance.py" in result.stdout


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
