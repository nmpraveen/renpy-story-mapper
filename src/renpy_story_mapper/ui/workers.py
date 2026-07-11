"""Cancellable Qt worker primitives used by project lifecycle operations."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QObject, QThread, Signal, Slot


class CancelCheck(Protocol):
    def __call__(self) -> bool: ...


class ProgressReporter(Protocol):
    def __call__(self, percent: int, status: str) -> None: ...


class OperationWorker(QObject):
    """Run one operation in a dedicated QThread with cooperative cancellation."""

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self, operation: Callable[[CancelCheck, ProgressReporter], object]
    ) -> None:
        super().__init__()
        self._operation = operation
        self._cancelled = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            result = self._operation(self._cancelled.is_set, self._report_progress)
        except BaseException as exc:
            self.failed.emit(exc)
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def cancel(self) -> None:
        self._cancelled.set()

    def _report_progress(self, percent: int, status: str) -> None:
        self.progress.emit(max(0, min(100, percent)), status)


class WorkerTask(QObject):
    """Own the QThread and worker lifetime for one background operation."""

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(object)
    finished = Signal()

    def __init__(
        self,
        operation: Callable[[CancelCheck, ProgressReporter], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = OperationWorker(operation)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress)
        self._worker.succeeded.connect(self.succeeded)
        self._worker.failed.connect(self.failed)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self.finished)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._worker.cancel()

    def is_running(self) -> bool:
        return self._thread.isRunning()

    def wait(self, milliseconds: int = 5000) -> bool:
        return self._thread.wait(milliseconds)
