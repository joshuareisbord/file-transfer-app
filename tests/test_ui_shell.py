import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from tkinter import ttk

import pytest

from work_transfer_app.config import SettingsStore
from work_transfer_app.localization import Translator
from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionTestedEvent,
    ConnectionTestResult,
    JobQueuedEvent,
    QueuePausedEvent,
    TransferErrorKind,
    TransferEvent,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferProgressEvent,
    TransferResult,
    TransferState,
    TransferStateEvent,
)
from work_transfer_app.ui.shell import WorkTransferWindow
from work_transfer_app.ui.status_tray import TransferStatusTray
from work_transfer_app.ui.styles import configure_styles


class FakeTransferController:
    """Provide the shell boundary without starting transfer infrastructure."""

    def __init__(self) -> None:
        """Create an empty event stream for the smoke test."""

        self.events: queue.Queue[TransferEvent] = queue.Queue()
        self.abort_started = threading.Event()
        self.allow_abort = threading.Event()
        self.resume_calls = 0

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Return a completed placeholder future."""

        _ = config
        return Future()

    def invalidate_connection(self) -> None:
        """Accept connection invalidation without state."""

    def enqueue(self, source: Path, remote_directory: str) -> TransferJob:
        """Reject queue use because this smoke test does not transfer files."""

        _ = (source, remote_directory)
        raise RuntimeError("not used")

    def remove(self, job_id: str) -> bool:
        """Report that no waiting job exists."""

        _ = job_id
        return False

    def abort(self) -> bool:
        """Hold cancellation so the test can exercise concurrent UI actions."""

        self.abort_started.set()
        return self.allow_abort.wait(timeout=2.0)

    def resume(self) -> bool:
        """Record any attempt to resume paused immutable work."""

        self.resume_calls += 1
        return False

    def shutdown(self, timeout: float = 5.0) -> None:
        """Accept shutdown without worker resources."""

        _ = timeout
        self.allow_abort.set()


def _descendants(widget: tk.Misc) -> list[tk.Misc]:
    """Return the Tk widget subtree below one parent."""

    descendants: list[tk.Misc] = []
    for child in widget.winfo_children():
        descendants.append(child)
        descendants.extend(_descendants(child))
    return descendants


def _pump_until(
    root: tk.Tk,
    predicate: Callable[[], bool],
    *,
    timeout: float = 1.0,
) -> None:
    """Process Tk events until a callable condition is true or time expires."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
    raise AssertionError("Tk condition was not reached before timeout")


def _label_text(label: ttk.Label) -> str:
    """Return text rendered directly or through a Tk variable."""

    direct_text = str(label.cget("text"))
    variable_name = str(label.cget("textvariable"))
    if direct_text or not variable_name:
        return direct_text
    return str(label.getvar(variable_name))


def test_shell_stays_interactive_during_progress_and_pending_abort(
    tmp_path: Path,
) -> None:
    """Exercise tab actions, progress, mismatch gating, and asynchronous abort."""

    controller: FakeTransferController | None = None
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")

    try:
        configure_styles(root)
        controller = FakeTransferController()
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("not json")
        settings = SettingsStore(path=settings_path)
        current_language = settings.load_language()
        translator = Translator("missing-language")
        window = WorkTransferWindow(
            root,
            controller,
            translator,
            settings,
            current_language,
        )
        root.update()
        root.focus_force()
        root.update()

        notebook = next(
            child
            for child in window.winfo_children()
            if isinstance(child, ttk.Notebook)
        )
        tray = next(
            child
            for child in window.winfo_children()
            if isinstance(child, TransferStatusTray)
        )
        assert [notebook.tab(tab_id, "text") for tab_id in notebook.tabs()] == [
            "Transfer",
            "Connection",
            "Settings",
        ]
        rendered_labels = [
            _label_text(child)
            for child in _descendants(window)
            if isinstance(child, ttk.Label)
        ]
        assert any("missing-language" in text for text in rendered_labels)
        assert any("Settings file is invalid" in text for text in rendered_labels)

        for index, expected in ((2, "Connection"), (3, "Settings"), (1, "Transfer")):
            window.event_generate(f"<Control-Key-{index}>")
            root.update()
            assert notebook.tab(notebook.select(), "text") == expected

        identity_file = tmp_path / "identity"
        known_hosts = tmp_path / "known_hosts"
        source = tmp_path / "payload.bin"
        identity_file.write_text("key")
        known_hosts.write_text("host key")
        source.write_bytes(b"0123456789")
        queued_config = ConnectionConfig(
            "queued.example",
            "operator",
            identity_file,
            known_hosts=known_hosts,
        )
        tested_config = ConnectionConfig(
            "tested.example",
            "operator",
            identity_file,
            known_hosts=known_hosts,
        )
        job = TransferJob("job-1", source, "/srv/incoming", queued_config)
        controller.events.put(JobQueuedEvent(job))
        controller.events.put(
            QueuePausedEvent("Connection lost", TransferErrorKind.CONNECTION)
        )
        controller.events.put(
            ConnectionTestedEvent(
                ConnectionTestResult(
                    tested_config,
                    True,
                    can_resume_queue=False,
                )
            )
        )
        controller.events.put(TransferStateEvent(job.id, TransferState.TRANSFERRING))
        controller.events.put(
            TransferProgressEvent(
                TransferProgress(
                    job.id,
                    transferred_bytes=5,
                    total_bytes=10,
                    percent=50.0,
                    bytes_per_second=5.0,
                    eta_seconds=1.0,
                )
            )
        )

        abort_button = next(
            child
            for child in _descendants(tray)
            if isinstance(child, ttk.Button) and child.cget("text") == "Abort"
        )
        _pump_until(root, lambda: abort_button.instate(["!disabled"]))

        assert controller.resume_calls == 0
        assert any(
            isinstance(child, ttk.Label)
            and "Remove and add them again" in _label_text(child)
            for child in _descendants(window)
        )
        assert any(
            isinstance(child, ttk.Label) and "50.0%" == _label_text(child)
            for child in _descendants(tray)
        )

        abort_button.invoke()
        _pump_until(root, controller.abort_started.is_set)
        window.event_generate("<Control-Key-3>")
        root.update()

        assert notebook.tab(notebook.select(), "text") == "Settings"
        assert tray.winfo_manager() == "grid"
        assert controller.allow_abort.is_set() is False

        controller.allow_abort.set()
        controller.events.put(
            TransferFinishedEvent(
                TransferResult(
                    job.id,
                    TransferState.FAILED,
                    "source_file_missing",
                    TransferErrorKind.FILE,
                )
            )
        )
        _pump_until(
            root,
            lambda: any(
                isinstance(child, ttk.Label)
                and "source file changed" in _label_text(child)
                for child in _descendants(window)
            ),
        )
        assert all(
            "source_file_missing" not in _label_text(child)
            for child in _descendants(window)
            if isinstance(child, ttk.Label)
        )
    finally:
        if controller is not None:
            controller.allow_abort.set()
        root.destroy()
