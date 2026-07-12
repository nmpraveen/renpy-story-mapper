"""Bounded Windows process boundary and content-addressed recovery cache."""

from __future__ import annotations

import ctypes
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from renpy_story_mapper.ingestion.contracts import (
    CancelCheck,
    IngestionOptions,
    SourceCandidate,
    SourceProvenance,
)
from renpy_story_mapper.ingestion.errors import (
    RecoveryError,
    RecoveryLimitError,
    RecoveryTimeoutError,
)

UNRPYC_VERSION: Final = "v2.0.4 tag (internal version 2.0.3)"
UNRPYC_COMMIT: Final = "3ae8334ed71a05535927dcc559663d3aca51215b"
UNRPYC_BUNDLE_SHA256: Final = "fb764521f9d3120b0c62198f086226f837802d73eccc9cad3c2ad683b1117775"
UNRPYC_BUNDLE_FILES: Final = (
    "decompiler/__init__.py",
    "decompiler/atldecompiler.py",
    "decompiler/magic.py",
    "decompiler/renpycompat.py",
    "decompiler/sl2decompiler.py",
    "decompiler/util.py",
    "LICENSE.txt",
)
LINE_BASIS: Final = "reconstructed_unrpyc_output_v1"


class _JobObject(AbstractContextManager["_JobObject"]):
    """Windows Job Object enforcing kill-on-close, memory, and one-process limits."""

    def __init__(self, memory_limit: int) -> None:
        if os.name != "nt":
            raise RecoveryError("compiled-source recovery is supported only on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32: Any = kernel32
        kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        )
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.TerminateJobObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise RecoveryError("could not create recovery Job Object")

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000 | 0x00000008 | 0x00000200
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        limits.ProcessMemoryLimit = memory_limit
        limits.JobMemoryLimit = memory_limit
        if not kernel32.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            self.close()
            raise RecoveryError("could not configure recovery Job Object")

    def assign_handle(self, process_handle: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, process_handle):
            raise RecoveryError("could not assign recovery helper to its Job Object")

    def terminate(self) -> None:
        if self._handle:
            self._kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _check_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        from renpy_story_mapper.storage import ProjectOperationCancelled

        raise ProjectOperationCancelled("compiled-source recovery was cancelled")


def _cache_key(candidate: SourceCandidate, options: IngestionOptions) -> str:
    value = {
        "input_sha256": candidate.input_hash,
        "tool_bundle_sha256": UNRPYC_BUNDLE_SHA256,
        "line_basis": LINE_BASIS,
        "max_output_bytes": options.max_output_bytes,
        "max_decompressed_bytes": options.max_decompressed_bytes,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_runtime_bundle() -> None:
    """Verify every pinned shipped runtime file; PIN.json is metadata, not hash input."""

    root = Path(__file__).resolve().parent / "_vendor" / "unrpyc"
    digest = hashlib.sha256()
    for relative in UNRPYC_BUNDLE_FILES:
        path = root / Path(relative)
        if not path.is_file():
            raise RecoveryError(f"pinned recovery runtime file is missing: {relative}")
        digest.update((relative + "\n").encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    if digest.hexdigest() != UNRPYC_BUNDLE_SHA256:
        raise RecoveryError("pinned recovery runtime bundle hash mismatch")


class _SuspendedProcess(AbstractContextManager["_SuspendedProcess"]):
    """Native suspended process, assigned to a Job before its first instruction runs."""

    def __init__(self, command: list[str], cwd: Path) -> None:
        if os.name != "nt":
            raise RecoveryError("compiled-source recovery is supported only on Windows")
        winapi: Any = importlib.import_module("_winapi")
        startup = subprocess.STARTUPINFO()
        flags = 0x00000004 | 0x08000000 | 0x00000400
        process_handle, thread_handle, _process_id, _thread_id = winapi.CreateProcess(
            command[0],
            subprocess.list2cmdline(command),
            None,
            None,
            False,
            flags,
            _sanitized_helper_environment(cwd),
            str(cwd),
            startup,
        )
        self._winapi = winapi
        self._kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.ResumeThread.argtypes = (ctypes.c_void_p,)
        self._kernel32.ResumeThread.restype = ctypes.c_uint32
        self.process_handle = int(process_handle)
        self.thread_handle = int(thread_handle)

    def resume(self) -> None:
        if self._kernel32.ResumeThread(self.thread_handle) == 0xFFFFFFFF:
            raise RecoveryError("could not resume bounded recovery helper")

    def poll(self) -> int | None:
        result = self._winapi.WaitForSingleObject(self.process_handle, 0)
        if result == 258:
            return None
        if result != 0:
            raise RecoveryError("could not wait for bounded recovery helper")
        return int(self._winapi.GetExitCodeProcess(self.process_handle))

    def wait_bounded(self, milliseconds: int) -> None:
        self._winapi.WaitForSingleObject(self.process_handle, milliseconds)

    def close(self) -> None:
        if self.thread_handle:
            self._winapi.CloseHandle(self.thread_handle)
            self.thread_handle = 0
        if self.process_handle:
            self._winapi.CloseHandle(self.process_handle)
            self.process_handle = 0

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _sanitized_helper_environment(work_root: Path) -> dict[str, str]:
    """Return the minimal non-secret environment inherited by the recovery helper."""

    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR") or r"C:\Windows"
    return {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "TEMP": str(work_root),
        "TMP": str(work_root),
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }


def recover_compiled(
    candidate: SourceCandidate,
    content: bytes,
    options: IngestionOptions,
    cancel_check: CancelCheck,
) -> tuple[bytes, SourceProvenance]:
    _check_cancelled(cancel_check)
    verify_runtime_bundle()
    if len(content) > options.max_input_bytes:
        raise RecoveryLimitError("compiled source exceeds configured input limit")
    if hashlib.sha256(content).hexdigest() != candidate.input_hash:
        raise RecoveryError("compiled source hash changed before recovery")
    cache_root = options.resolved_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    key = _cache_key(candidate, options)
    entry_root = cache_root / key[:2] / key
    cached_output = entry_root / "source.rpy"
    cached_record = entry_root / "provenance.json"
    if cached_output.is_file() and cached_record.is_file():
        output = cached_output.read_bytes()
        raw = json.loads(cached_record.read_text(encoding="utf-8"))
        if (
            len(output) <= options.max_output_bytes
            and hashlib.sha256(output).hexdigest() == raw.get("output_sha256")
            and raw.get("input_sha256") == candidate.input_hash
            and raw.get("tool_bundle_sha256") == UNRPYC_BUNDLE_SHA256
        ):
            provenance = _provenance(candidate, output, raw, cache_hit=True)
            return output, provenance
        shutil.rmtree(entry_root, ignore_errors=True)

    cache_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rsm-recovery-", dir=cache_root) as temporary:
        work_root = Path(temporary)
        (work_root / "input.rpyc").write_bytes(content)
        request = {
            "input_name": "input.rpyc",
            "output_name": "source.rpy",
            "max_input_bytes": options.max_input_bytes,
            "max_output_bytes": options.max_output_bytes,
            "max_decompressed_bytes": options.max_decompressed_bytes,
            "max_log_bytes": options.max_log_bytes,
        }
        (work_root / "request.json").write_text(
            json.dumps(request, sort_keys=True), encoding="utf-8"
        )
        helper = Path(__file__).with_name("helper.py").resolve(strict=True)
        base_executable = str(getattr(sys, "_base_executable", sys.executable))
        command = [base_executable, "-I", "-S", "-B", str(helper), str(work_root)]
        started = time.monotonic()
        with (
            _JobObject(options.max_memory_bytes) as job,
            _SuspendedProcess(command, work_root) as process,
        ):
            try:
                job.assign_handle(process.process_handle)
                process.resume()
                while process.poll() is None:
                    _check_cancelled(cancel_check)
                    if time.monotonic() - started > options.recovery_timeout_seconds:
                        job.terminate()
                        raise RecoveryTimeoutError("compiled-source recovery timed out")
                    time.sleep(0.02)
            except BaseException:
                job.terminate()
                process.wait_bounded(5000)
                raise
        result_path = work_root / "result.json"
        if not result_path.is_file() or result_path.stat().st_size > options.max_log_bytes:
            raise RecoveryError("recovery helper returned no bounded result")
        raw_result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(raw_result, dict) or raw_result.get("status") != "ok":
            message = (
                raw_result.get("error", "recovery helper failed")
                if isinstance(raw_result, dict)
                else "recovery helper failed"
            )
            raise RecoveryError(str(message))
        output_path = work_root / "source.rpy"
        if not output_path.is_file() or output_path.stat().st_size > options.max_output_bytes:
            raise RecoveryLimitError("recovery helper output is missing or oversized")
        output = output_path.read_bytes()
        if hashlib.sha256(output).hexdigest() != raw_result.get("output_sha256"):
            raise RecoveryError("recovery helper output hash mismatch")
        complete = bool(raw_result.get("complete"))
        if not complete and not options.allow_partial_recovery:
            raise RecoveryError("compiled source recovery was incomplete under strict policy")
        record = {
            **raw_result,
            "locator": candidate.locator,
            "tool_name": "Unrpyc minimal runtime",
            "tool_version": UNRPYC_VERSION,
            "tool_commit": UNRPYC_COMMIT,
            "tool_bundle_sha256": UNRPYC_BUNDLE_SHA256,
            "line_basis": LINE_BASIS,
            "options": request,
        }
        entry_root.parent.mkdir(parents=True, exist_ok=True)
        staged = entry_root.with_name(f".{entry_root.name}.{os.getpid()}.tmp")
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir()
        (staged / "source.rpy").write_bytes(output)
        (staged / "provenance.json").write_text(
            json.dumps(record, sort_keys=True), encoding="utf-8"
        )
        try:
            staged.replace(entry_root)
        except FileExistsError:
            shutil.rmtree(staged, ignore_errors=True)
        return output, _provenance(candidate, output, record, cache_hit=False)


def _provenance(
    candidate: SourceCandidate,
    output: bytes,
    record: dict[str, object],
    *,
    cache_hit: bool,
) -> SourceProvenance:
    warnings = record.get("warnings", [])
    raw_options = record.get("options")
    provenance_options = raw_options if isinstance(raw_options, dict) else {}
    return SourceProvenance(
        source_kind="reconstructed",
        locator=candidate.locator,
        tier=candidate.tier,
        input_sha256=candidate.input_hash,
        output_sha256=hashlib.sha256(output).hexdigest(),
        line_basis=LINE_BASIS,
        tool_name="Unrpyc minimal runtime",
        tool_version=UNRPYC_VERSION,
        tool_commit=UNRPYC_COMMIT,
        tool_bundle_sha256=UNRPYC_BUNDLE_SHA256,
        options=provenance_options,
        cache_hit=cache_hit,
        complete=bool(record.get("complete", True)),
        warnings=tuple(str(item) for item in warnings) if isinstance(warnings, list) else (),
    )
