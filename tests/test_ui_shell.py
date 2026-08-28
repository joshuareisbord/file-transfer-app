import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import Future
from pathlib import Path
from tkinter import ttk

import pytest

from work_transfer_app.config import (
    MockTestDefinition,
    SettingsStore,
    UpdateDestinations,
)
from work_transfer_app.localization import Translator
from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionDegradedEvent,
    ConnectionTestedEvent,
    ConnectionTestResult,
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
from work_transfer_app.ui.logo import prepare_header_logo
from work_transfer_app.ui.shell import WorkTransferWindow, create_window
from work_transfer_app.ui.status_tray import TransferStatusTray
from work_transfer_app.ui.styles import configure_styles


class FakeTransferController:
    """Provide one controllable transfer slot at the shell boundary."""

    def __init__(self, connection: ConnectionConfig) -> None:
        """Create an event stream and record transfer control operations."""

        self.events: queue.Queue[TransferEvent] = queue.Queue()
        self.connection = connection
        self.start_calls: list[tuple[Path, str]] = []
        self.abort_started = threading.Event()
        self.allow_abort = threading.Event()

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Return an incomplete placeholder future while events drive the UI."""

        _ = config
        return Future()

    def invalidate_connection(self) -> None:
        """Accept connection invalidation without controller state."""

    def start(self, source: Path, remote_directory: str) -> TransferJob:
        """Return a deterministic job and record its fixed destination."""

        self.start_calls.append((source.resolve(), remote_directory))
        return TransferJob("job-1", source, remote_directory, self.connection)

    def abort(self) -> bool:
        """Hold cancellation so tab navigation can be tested concurrently."""

        self.abort_started.set()
        return self.allow_abort.wait(timeout=2.0)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Release pending cancellation without worker resources."""

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


def _find_button(parent: tk.Misc, text: str) -> ttk.Button:
    """Return one descendant button with exact visible text."""

    return next(
        child
        for child in _descendants(parent)
        if isinstance(child, ttk.Button) and child.cget("text") == text
    )


def _history_rows(parent: tk.Misc) -> list[tuple[str, ...]]:
    """Return every visible Treeview row in one update page."""

    tree = next(
        child for child in _descendants(parent) if isinstance(child, ttk.Treeview)
    )
    return [tuple(tree.item(item, "values")) for item in tree.get_children()]


def test_shell_supports_five_tabs_single_transfer_history_and_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise navigation, fixed destination, progress, Abort, log, and health."""

    controller: FakeTransferController | None = None
    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")

    try:
        identity_file = tmp_path / "identity"
        known_hosts = tmp_path / "known_hosts"
        source = tmp_path / "library-update.bin"
        logo_path = tmp_path / "brand.svg"
        identity_file.write_text("key")
        known_hosts.write_text("host key")
        source.write_bytes(b"0123456789")
        logo_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            '<rect width="10" height="10" fill="#E7DBC4"/></svg>',
            encoding="utf-8",
        )
        connection = ConnectionConfig(
            "receiver.example",
            "operator",
            identity_file,
            known_hosts=known_hosts,
        )

        configure_styles(root)
        controller = FakeTransferController(connection)
        settings = SettingsStore(path=tmp_path / "settings.json")
        translator = Translator()
        window = WorkTransferWindow(
            root,
            controller,
            translator,
            settings,
            settings.load_language(),
            UpdateDestinations("~/library-updates", "~/software-updates"),
            (MockTestDefinition("demo", "Demonstration test"),),
            header_logo=prepare_header_logo(logo_path),
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
            "Library Update",
            "SW Update",
            "Test",
            "Connection",
            "Settings",
        ]
        logo_label = next(
            child
            for child in _descendants(window)
            if isinstance(child, tk.Label) and child.cget("image")
        )
        assert logo_label.grid_info()["column"] == 0
        assert logo_label.cget("image")
        assert logo_label.cget("borderwidth") == 0
        assert logo_label.cget("highlightthickness") == 0

        for shortcut, expected in enumerate(
            ("Library Update", "SW Update", "Test", "Connection", "Settings"),
            start=1,
        ):
            window.event_generate(f"<Control-Key-{shortcut}>")
            root.update()
            assert notebook.tab(notebook.select(), "text") == expected

        rendered_labels = [
            _label_text(child)
            for child in _descendants(window)
            if isinstance(child, ttk.Label)
        ]
        assert "Disconnected" in rendered_labels

        controller.events.put(
            ConnectionTestedEvent(ConnectionTestResult(connection, True))
        )
        _pump_until(
            root,
            lambda: (
                "Connected"
                in [
                    _label_text(child)
                    for child in _descendants(window)
                    if isinstance(child, ttk.Label)
                ]
            ),
        )

        library_tab = window._library_update_tab
        software_tab = window._software_update_tab
        monkeypatch.setattr(
            "work_transfer_app.ui.tabs.filedialog.askopenfilename",
            lambda **_kwargs: str(source),
        )
        _find_button(library_tab, "Browse").invoke()
        _find_button(library_tab, "Start library update").invoke()
        root.update()

        assert controller.start_calls == [(source.resolve(), "~/library-updates")]
        assert _find_button(library_tab, "Start library update").instate(["disabled"])
        assert _find_button(software_tab, "Start software update").instate(["disabled"])

        controller.events.put(TransferStateEvent("job-1", TransferState.TRANSFERRING))
        controller.events.put(
            TransferProgressEvent(
                TransferProgress(
                    "job-1",
                    transferred_bytes=5,
                    total_bytes=10,
                    percent=50.0,
                    bytes_per_second=5.0,
                    eta_seconds=1.0,
                )
            )
        )
        abort_button = _find_button(tray, "Abort")
        _pump_until(root, lambda: abort_button.instate(["!disabled"]))
        abort_button.invoke()
        _pump_until(root, controller.abort_started.is_set)
        window.event_generate("<Control-Key-5>")
        root.update()
        assert notebook.tab(notebook.select(), "text") == "Settings"
        assert controller.allow_abort.is_set() is False

        controller.allow_abort.set()
        controller.events.put(
            TransferFinishedEvent(TransferResult("job-1", TransferState.COMPLETED))
        )
        _pump_until(root, lambda: bool(_history_rows(library_tab)))
        assert _history_rows(library_tab) == [("library-update.bin", "Completed")]
        assert _history_rows(software_tab) == []

        controller.events.put(
            ConnectionDegradedEvent("Connection lost", TransferErrorKind.CONNECTION)
        )
        _pump_until(
            root,
            lambda: (
                "Degraded"
                in [
                    _label_text(child)
                    for child in _descendants(window)
                    if isinstance(child, ttk.Label)
                ]
            ),
        )
        assert _find_button(library_tab, "Start library update").instate(["disabled"])
    finally:
        if controller is not None:
            controller.allow_abort.set()
        root.destroy()


def test_close_timeout_keeps_window_open_and_reports_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A slow remote cleanup stays off Tk and leaves a retryable window."""

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")

    identity_file = tmp_path / "identity"
    known_hosts = tmp_path / "known_hosts"
    identity_file.write_text("key")
    known_hosts.write_text("host key")
    connection = ConnectionConfig(
        "receiver.example",
        "operator",
        identity_file,
        known_hosts=known_hosts,
    )
    controller = FakeTransferController(connection)
    shutdown_started = threading.Event()
    messages: list[tuple[str, str]] = []

    def timeout_shutdown(timeout: float = 5.0) -> None:
        """Model controller cleanup which exceeds the close deadline."""

        _ = timeout
        shutdown_started.set()
        raise TimeoutError("shutdown_cleanup_timeout")

    monkeypatch.setattr(controller, "shutdown", timeout_shutdown)
    monkeypatch.setattr(
        "work_transfer_app.ui.shell.messagebox.showerror",
        lambda *, title, message, parent: messages.append((title, message)),
    )

    try:
        configure_styles(root)
        settings = SettingsStore(path=tmp_path / "settings.json")
        window = WorkTransferWindow(
            root,
            controller,
            Translator(),
            settings,
            settings.load_language(),
            UpdateDestinations("~/library-updates", "~/software-updates"),
            (MockTestDefinition("demo", "Demonstration test"),),
        )
        root.update()

        window._close_requested()

        assert shutdown_started.wait(timeout=1)
        _pump_until(root, lambda: bool(messages))
        assert messages == [
            (
                "Cleanup incomplete",
                (
                    "Work Transfer is still cleaning the incomplete remote file. "
                    "Wait, then close the application again."
                ),
            )
        ]
        assert root.winfo_exists() == 1
        assert window._is_shutdown_pending is False
    finally:
        controller.allow_abort.set()
        root.destroy()


def test_create_window_shuts_down_owned_controller_when_window_build_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup failure releases the controller created by the window factory."""

    try:
        display_probe = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    display_probe.destroy()

    class OwnedController:
        """Record cleanup for a controller owned by create_window."""

        def __init__(self) -> None:
            """Register the created controller."""

            self.shutdown_calls = 0
            created_controllers.append(self)

        def shutdown(self, timeout: float = 5.0) -> None:
            """Record owned-controller cleanup."""

            _ = timeout
            self.shutdown_calls += 1

    created_controllers: list[OwnedController] = []

    def fail_window_build(*_args: object, **_kwargs: object) -> None:
        """Model a Tk widget construction failure after controller startup."""

        raise RuntimeError("window build failed")

    monkeypatch.setattr(
        "work_transfer_app.transfer.TransferController",
        OwnedController,
    )
    monkeypatch.setattr(
        "work_transfer_app.ui.shell.WorkTransferWindow",
        fail_window_build,
    )

    with pytest.raises(RuntimeError, match="window build failed"):
        create_window(
            translator=Translator(),
            settings=SettingsStore(path=tmp_path / "settings.json"),
            update_destinations=UpdateDestinations(
                "~/library-updates",
                "~/software-updates",
            ),
            mock_tests=(),
        )

    assert len(created_controllers) == 1
    assert created_controllers[0].shutdown_calls == 1
