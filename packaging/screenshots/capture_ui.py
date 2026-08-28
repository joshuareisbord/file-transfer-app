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
        """Create deterministic state required by the shell contract."""

        self.events: queue.Queue[TransferEvent] = queue.Queue()
        self._connection: ConnectionConfig | None = None
        self.last_started: TransferJob | None = None

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Return an immediately successful result for screenshot controls."""

        future: Future[ConnectionTestResult] = Future()
        future.set_result(ConnectionTestResult(config, True))
        return future

    def invalidate_connection(self) -> None:
        """Accept visible connection edits without background state."""

        self._connection = None

    def accept_connection(self, config: ConnectionConfig) -> None:
        """Retain the tested connection used by synthetic transfer starts."""

        self._connection = config

    def start(self, source: Path, remote_directory: str) -> TransferJob:
        """Create one job without starting network work."""

        if self._connection is None:
            raise RuntimeError("connection_not_tested")
        self.last_started = TransferJob.create(
            source,
            remote_directory,
            self._connection,
        )
        return self.last_started

    def abort(self) -> bool:
        """Accept the synthetic active transfer cancellation action."""

        return True

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
    window: WorkTransferWindow,
    controller: ScreenshotController,
    root_directory: Path,
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
    controller.accept_connection(config)
    window._dispatch_event(ConnectionTestedEvent(ConnectionTestResult(config, True)))
    return config


def _start_synthetic_transfer(
    window: WorkTransferWindow,
    controller: ScreenshotController,
    tab_name: str,
    source: Path,
) -> TransferJob:
    """Start a transfer through the same tab action used in production."""

    tab = (
        window._library_update_tab
        if tab_name == "library"
        else window._software_update_tab
    )
    controller.last_started = None
    tab._source_path = source
    tab._source_display.set(str(source))
    tab._start_transfer()
    if controller.last_started is None:
        raise RuntimeError("Synthetic transfer did not start")
    return controller.last_started


def _populate_completed_transfer(
    window: WorkTransferWindow,
    controller: ScreenshotController,
    root_directory: Path,
    tab_name: str,
    filename: str,
    size: int,
) -> None:
    """Add one successful transfer to the selected page's session history."""

    source = root_directory / filename
    _create_sparse_file(source, size)
    job = _start_synthetic_transfer(window, controller, tab_name, source)
    window._dispatch_event(
        TransferFinishedEvent(TransferResult(job.id, TransferState.COMPLETED))
    )


def _populate_test_results(window: WorkTransferWindow) -> None:
    """Show readable pass and fail examples without waiting on random timers."""

    test_ids = tuple(window._test_tab._status_variables)
    for index, test_id in enumerate(test_ids):
        window._test_tab._set_test_state(
            test_id,
            "fail" if index == len(test_ids) - 1 else "pass",
        )


def _populate_active_transfer(
    window: WorkTransferWindow,
    controller: ScreenshotController,
    root_directory: Path,
) -> None:
    """Drive the shell event path into a representative active state."""

    active_source = root_directory / "factory-calibration-archive.tar.gz"
    _create_sparse_file(active_source, 700 * MIB)
    active_job = _start_synthetic_transfer(
        window,
        controller,
        "library",
        active_source,
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
        controller = ScreenshotController()
        logo_path = (
            Path(__file__).resolve().parents[2]
            / "packaging/demo/work-transfer-mark.svg"
        )
        root = create_window(
            controller,
            Translator("en"),
            SettingsStore(path=root_directory / "settings.json"),
            logo_path=logo_path,
        )
        try:
            root.geometry("980x760+0+0")
            root.update()
            window = next(
                child
                for child in root.winfo_children()
                if isinstance(child, WorkTransferWindow)
            )

            _populate_connection(window, controller, root_directory)
            _populate_completed_transfer(
                window,
                controller,
                root_directory,
                "library",
                "library-package-2026-08-27.tar",
                24 * MIB,
            )
            window._notebook.select(0)
            _capture(root, output_directory / "01-library-update.png")

            _populate_completed_transfer(
                window,
                controller,
                root_directory,
                "software",
                "control-software-4.8.0.pkg",
                41 * MIB,
            )
            window._notebook.select(1)
            _capture(root, output_directory / "02-software-update.png")

            _populate_test_results(window)
            window._notebook.select(2)
            _capture(root, output_directory / "03-test.png")

            window._notebook.select(3)
            _capture(root, output_directory / "04-connection-tested.png")

            window._notebook.select(4)
            _capture(root, output_directory / "05-settings.png")

            _populate_active_transfer(window, controller, root_directory)
            window._notebook.select(0)
            _capture(root, output_directory / "06-library-update-active.png")
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
