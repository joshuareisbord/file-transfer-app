"""Capture deterministic Ubuntu screenshots of the production Tk interface."""

from __future__ import annotations

import queue
import subprocess
import sys
import tempfile
from concurrent.futures import Future
from pathlib import Path

from work_transfer_app.config import SettingsStore
from work_transfer_app.localization import Translator
from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionTestedEvent,
    ConnectionTestResult,
    JobQueuedEvent,
    TransferEvent,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferProgressEvent,
    TransferResult,
    TransferState,
    TransferStateEvent,
)
from work_transfer_app.ui import create_window
from work_transfer_app.ui.shell import WorkTransferWindow

MIB = 1024 * 1024


class ScreenshotController:
    """Provide the UI controller boundary without starting network work."""

    def __init__(self) -> None:
        """Create the unused event queue required by the shell contract."""

        self.events: queue.Queue[TransferEvent] = queue.Queue()

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Return an immediately successful result for screenshot controls."""

        future: Future[ConnectionTestResult] = Future()
        future.set_result(ConnectionTestResult(config, True))
        return future

    def invalidate_connection(self) -> None:
        """Accept visible connection edits without background state."""

    def enqueue(self, source: Path, remote_directory: str) -> TransferJob:
        """Reject real queue use because screenshot state is event-driven."""

        _ = (source, remote_directory)
        raise RuntimeError("Screenshot controller does not enqueue files")

    def remove(self, job_id: str) -> bool:
        """Report that no synthetic row was removed."""

        _ = job_id
        return False

    def abort(self) -> bool:
        """Accept the synthetic active transfer cancellation action."""

        return True

    def resume(self) -> bool:
        """Report that no synthetic paused queue was resumed."""

        return False

    def shutdown(self, timeout: float = 5.0) -> None:
        """Accept window shutdown without worker resources."""

        _ = timeout


def _capture(root: object, output: Path) -> None:
    """Render pending Tk work and capture only the application window."""

    from tkinter import Tk

    if not isinstance(root, Tk):
        raise TypeError("Expected a Tk root window")
    root.update_idletasks()
    root.update()
    root.focus_force()
    root.update()
    subprocess.run(
        [
            "scrot",
            "--overwrite",
            "--window",
            str(root.winfo_id()),
            str(output),
        ],
        check=True,
    )


def _create_sparse_file(path: Path, size: int) -> None:
    """Create a size-realistic local file without writing its full contents."""

    with path.open("wb") as file:
        file.truncate(size)


def _populate_connection(
    window: WorkTransferWindow, root_directory: Path
) -> ConnectionConfig:
    """Show realistic direct-Ethernet SSH details in a successful state."""

    identity_file = root_directory / "work_transfer"
    known_hosts = root_directory / "known_hosts"
    identity_file.write_text("screenshot key", encoding="utf-8")
    known_hosts.write_text("screenshot host", encoding="utf-8")

    connection_tab = window._connection_tab
    connection_tab._host.set("192.168.50.2")
    connection_tab._username.set("receiver")
    connection_tab._port.set("22")
    connection_tab._identity_file.set("/home/operator/.ssh/work_transfer")

    config = ConnectionConfig(
        host="192.168.50.2",
        username="receiver",
        port=22,
        identity_file=identity_file,
        known_hosts=known_hosts,
    )
    window._dispatch_event(ConnectionTestedEvent(ConnectionTestResult(config, True)))
    return config


def _populate_active_transfer(
    window: WorkTransferWindow,
    root_directory: Path,
    config: ConnectionConfig,
) -> None:
    """Drive the real shell event path into a representative active state."""

    active_source = root_directory / "factory-calibration-archive.tar.gz"
    queued_source = root_directory / "diagnostic-logs.csv"
    completed_source = root_directory / "shift-report.pdf"
    _create_sparse_file(active_source, 700 * MIB)
    _create_sparse_file(queued_source, 18 * MIB)
    _create_sparse_file(completed_source, 3 * MIB)

    active_job = TransferJob(
        "capture-active",
        active_source,
        "/srv/work-transfer/incoming",
        config,
    )
    queued_job = TransferJob(
        "capture-queued",
        queued_source,
        "/srv/work-transfer/incoming",
        config,
    )
    completed_job = TransferJob(
        "capture-completed",
        completed_source,
        "/srv/work-transfer/reports",
        config,
    )
    for job in (active_job, queued_job, completed_job):
        window._dispatch_event(JobQueuedEvent(job))
    window._dispatch_event(
        TransferFinishedEvent(TransferResult(completed_job.id, TransferState.COMPLETED))
    )
    window._dispatch_event(
        TransferStateEvent(active_job.id, TransferState.TRANSFERRING)
    )
    window._dispatch_event(
        TransferProgressEvent(
            TransferProgress(
                active_job.id,
                transferred_bytes=300 * MIB,
                total_bytes=700 * MIB,
                percent=42.9,
                bytes_per_second=12.8 * MIB,
                eta_seconds=31.5,
            )
        )
    )


def main() -> None:
    """Capture every primary tab and the persistent active-transfer tray."""

    output_directory = Path(sys.argv[1]).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="work-transfer-screenshots-") as directory:
        root_directory = Path(directory)
        sys.__dict__["frozen"] = True
        root = create_window(
            ScreenshotController(),
            Translator("en"),
            SettingsStore(path=root_directory / "settings.json"),
        )
        try:
            root.geometry("980x760+0+0")
            root.update()
            window = next(
                child
                for child in root.winfo_children()
                if isinstance(child, WorkTransferWindow)
            )

            window._notebook.select(0)
            _capture(root, output_directory / "01-transfer-idle.png")

            config = _populate_connection(window, root_directory)
            window._notebook.select(1)
            _capture(root, output_directory / "02-connection-tested.png")

            window._notebook.select(2)
            _capture(root, output_directory / "03-settings.png")

            _populate_active_transfer(window, root_directory, config)
            window._notebook.select(0)
            _capture(root, output_directory / "04-transfer-active.png")
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
