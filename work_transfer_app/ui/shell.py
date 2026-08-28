"""Application shell coordinating tabs with background transfer events."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from functools import partial
from pathlib import Path
from tkinter import messagebox, ttk
from typing import cast

from PIL import Image, ImageTk

from work_transfer_app.config import MockTestDefinition, UpdateDestinations
from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionDegradedEvent,
    ConnectionTestedEvent,
    ConnectionTestResult,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferProgressEvent,
    TransferState,
    TransferStateEvent,
)
from work_transfer_app.ui.contracts import (
    SettingsLike,
    TransferControllerLike,
    TranslatorLike,
)
from work_transfer_app.ui.logo import create_tk_header_logo, prepare_header_logo
from work_transfer_app.ui.messages import localized_backend_message
from work_transfer_app.ui.status_tray import TransferStatusTray
from work_transfer_app.ui.styles import configure_styles
from work_transfer_app.ui.tabs import (
    ConnectionTab,
    SettingsTab,
    TestTab,
    UpdateTransferTab,
)

_EVENT_POLL_MS = 250


class WorkTransferWindow(ttk.Frame):
    """Coordinate five fixed tabs with a persistent transfer status tray."""

    def __init__(
        self,
        root: tk.Tk,
        controller: TransferControllerLike,
        translator: TranslatorLike,
        settings: SettingsLike,
        current_language: str,
        update_destinations: UpdateDestinations,
        mock_tests: tuple[MockTestDefinition, ...],
        *,
        header_logo: Image.Image | None = None,
    ) -> None:
        """Build the UI and begin polling its background event boundary."""

        super().__init__(root, style="Body.TFrame")
        self._tk_root = root
        self._controller = controller
        self._translator = translator
        self._jobs: dict[str, TransferJob] = {}
        self._job_owners: dict[str, UpdateTransferTab] = {}
        self._active_job_id: str | None = None
        self._is_connection_ready = False
        self._abort_results: queue.Queue[bool] = queue.Queue()
        self._shutdown_results: queue.Queue[BaseException | None] = queue.Queue()
        self._event_poll_id: str | None = None
        self._is_closing = False
        self._is_shutdown_pending = False
        self._header_logo_image: ImageTk.PhotoImage | None = None
        self._build(
            settings,
            current_language,
            update_destinations,
            mock_tests,
            header_logo,
        )
        self._bind_keyboard_navigation()
        self._tk_root.protocol("WM_DELETE_WINDOW", self._close_requested)
        self._schedule_event_poll()

    def _build(
        self,
        settings: SettingsLike,
        current_language: str,
        update_destinations: UpdateDestinations,
        mock_tests: tuple[MockTestDefinition, ...],
        header_logo: Image.Image | None,
    ) -> None:
        """Lay out the header, fixed tab body, and transfer status tray."""

        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 13))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        brand = ttk.Frame(header, style="HeaderContent.TFrame")
        brand.grid(row=0, column=0, rowspan=2, sticky="w")
        text_column = 0
        if header_logo is not None:
            self._header_logo_image = create_tk_header_logo(brand, header_logo)
            tk.Label(
                brand,
                image=self._header_logo_image,
                background=ttk.Style(brand).lookup(
                    "HeaderContent.TFrame", "background"
                ),
                borderwidth=0,
                highlightthickness=0,
                padx=0,
                pady=0,
                relief="flat",
            ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
            text_column = 1
        ttk.Label(
            brand,
            text=self._translator.t("app.title"),
            style="AppTitle.TLabel",
        ).grid(row=0, column=text_column, sticky="w")
        ttk.Label(
            brand,
            text=self._translator.t("app.subtitle"),
            style="AppSubtitle.TLabel",
        ).grid(row=1, column=text_column, sticky="w", pady=(2, 0))

        health = ttk.Frame(header, style="HeaderContent.TFrame")
        health.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(
            health,
            text=self._translator.t("connection_health.label"),
            style="AppSubtitle.TLabel",
        ).grid(row=0, column=0, sticky="e", padx=(0, 10))
        self._connection_health = ttk.Label(health)
        self._connection_health.grid(row=0, column=1, sticky="e")
        self._set_connection_health("disconnected")

        self._notebook = ttk.Notebook(self, takefocus=True)
        self._notebook.grid(row=1, column=0, sticky="nsew")
        self._library_update_tab = UpdateTransferTab(
            self._notebook,
            self._translator,
            "library_update",
            update_destinations.library_update,
            self._start_library_transfer,
        )
        self._software_update_tab = UpdateTransferTab(
            self._notebook,
            self._translator,
            "software_update",
            update_destinations.software_update,
            self._start_software_transfer,
        )
        self._test_tab = TestTab(self._notebook, self._translator, mock_tests)
        self._connection_tab = ConnectionTab(
            self._notebook,
            self._translator,
            self._test_connection,
            self._connection_invalidated,
        )
        self._settings_tab = SettingsTab(
            self._notebook,
            self._translator,
            settings,
            current_language,
        )
        for tab, translation_key in (
            (self._library_update_tab, "tabs.library_update"),
            (self._software_update_tab, "tabs.software_update"),
            (self._test_tab, "tabs.test"),
            (self._connection_tab, "tabs.connection"),
            (self._settings_tab, "tabs.settings"),
        ):
            self._notebook.add(tab, text=self._translator.t(translation_key))
        self._notebook.enable_traversal()

        self._status_tray = TransferStatusTray(
            self,
            self._translator,
            self._abort_transfer,
        )
        self._status_tray.grid(row=2, column=0, sticky="ew")

    def _bind_keyboard_navigation(self) -> None:
        """Provide stable shortcuts for switching the five primary tabs."""

        for position in range(5):
            self._tk_root.bind(
                f"<Control-Key-{position + 1}>",
                partial(self._select_tab, position),
            )

    def _select_tab(self, index: int, _event: tk.Event[tk.Misc]) -> str:
        """Select one tab from its keyboard shortcut."""

        self._notebook.select(index)
        return "break"

    def _start_library_transfer(
        self,
        source: Path,
        remote_directory: str,
    ) -> TransferJob:
        """Start a library update owned by the Library Update page."""

        return self._start_transfer(
            self._library_update_tab,
            source,
            remote_directory,
        )

    def _start_software_transfer(
        self,
        source: Path,
        remote_directory: str,
    ) -> TransferJob:
        """Start a software update owned by the SW Update page."""

        return self._start_transfer(
            self._software_update_tab,
            source,
            remote_directory,
        )

    def _start_transfer(
        self,
        owner: UpdateTransferTab,
        source: Path,
        remote_directory: str,
    ) -> TransferJob:
        """Reserve the single transfer slot and associate it with its page."""

        job = self._controller.start(source, remote_directory)
        self._jobs[job.id] = job
        self._job_owners[job.id] = owner
        self._active_job_id = job.id
        self._refresh_transfer_gates()
        self._status_tray.show_connecting(job.source.name)
        return job

    def _test_connection(
        self,
        host: str,
        username: str,
        port: int,
        identity_file: Path,
    ) -> None:
        """Create an immutable connection snapshot and test it asynchronously."""

        config = ConnectionConfig(
            host=host,
            username=username,
            port=port,
            identity_file=identity_file,
        )
        self._controller.test_connection(config)

    def _connection_invalidated(self) -> None:
        """Close the transfer gate after session connection fields are edited."""

        self._controller.invalidate_connection()
        self._is_connection_ready = False
        self._set_connection_health("disconnected")
        self._refresh_transfer_gates()

    def _abort_transfer(self) -> None:
        """Request cancellation without blocking the Tk event loop."""

        job = self._active_job()
        if job is None:
            return
        self._status_tray.show_cancelling(job.source.name)
        threading.Thread(
            target=self._abort_on_worker,
            name="work-transfer-abort",
            daemon=True,
        ).start()

    def _abort_on_worker(self) -> None:
        """Wait for controller cancellation away from Tk and publish its outcome."""

        try:
            was_aborted = self._controller.abort()
        except (RuntimeError, TimeoutError):
            was_aborted = False
        self._abort_results.put(was_aborted)

    def _schedule_event_poll(self) -> None:
        """Poll transfer events at no more than four UI refreshes per second."""

        self._event_poll_id = self._tk_root.after(
            _EVENT_POLL_MS,
            self._poll_controller_events,
        )

    def _poll_controller_events(self) -> None:
        """Drain immutable worker events only from the Tk thread."""

        if self._is_closing:
            return
        self._drain_abort_results()
        if self._drain_shutdown_results():
            return
        while True:
            try:
                event = self._controller.events.get_nowait()
            except queue.Empty:
                break
            self._dispatch_event(event)
        self._schedule_event_poll()

    def _drain_abort_results(self) -> None:
        """Restore status when a raced cancellation request was rejected."""

        while True:
            try:
                was_aborted = self._abort_results.get_nowait()
            except queue.Empty:
                return
            if not was_aborted:
                self._restore_active_status()

    def _drain_shutdown_results(self) -> bool:
        """Finish closing or report a cleanup timeout from the worker thread."""

        try:
            error = self._shutdown_results.get_nowait()
        except queue.Empty:
            return False
        if error is None:
            self._is_closing = True
            self._event_poll_id = None
            self._tk_root.destroy()
            return True

        self._is_shutdown_pending = False
        messagebox.showerror(
            title=self._translator.t("dialogs.cleanup_title"),
            message=self._translator.t("dialogs.cleanup_message"),
            parent=self._tk_root,
        )
        return False

    def _restore_active_status(self) -> None:
        """Restore connecting status after a rejected cancellation request."""

        job = self._active_job()
        if job is None:
            self._status_tray.show_idle()
        else:
            self._status_tray.show_connecting(job.source.name)

    def _active_job(self) -> TransferJob | None:
        """Return the active job known to the UI, if one exists."""

        if self._active_job_id is None:
            return None
        return self._jobs.get(self._active_job_id)

    def _dispatch_event(self, event: object) -> None:
        """Route a controller event to the smallest affected UI component."""

        if isinstance(event, ConnectionTestedEvent):
            self._handle_connection_tested(event.result)
        elif isinstance(event, TransferStateEvent):
            self._handle_transfer_state(event)
        elif isinstance(event, TransferProgressEvent):
            self._handle_transfer_progress(event.progress)
        elif isinstance(event, TransferFinishedEvent):
            self._handle_transfer_finished(event)
        elif isinstance(event, ConnectionDegradedEvent):
            self._handle_connection_degraded(event)

    def _handle_connection_tested(self, result: ConnectionTestResult) -> None:
        """Update connection health and transfer gating after a test."""

        if result.is_stale:
            return
        if result.is_success:
            self._connection_tab.mark_tested(True)
            self._is_connection_ready = True
            self._set_connection_health("connected")
            self._refresh_transfer_gates()
            return

        self._is_connection_ready = False
        self._set_connection_health("disconnected")
        self._refresh_transfer_gates()
        if result.message == "connection_invalidated":
            return
        self._connection_tab.mark_tested(
            False,
            localized_backend_message(
                self._translator,
                result.message,
                result.error_kind,
                context="connection",
            ),
        )

    def _handle_transfer_state(self, event: TransferStateEvent) -> None:
        """Update the bottom tray for a non-terminal transfer state."""

        job = self._jobs.get(event.job_id)
        if job is None or event.job_id != self._active_job_id:
            return
        if event.state is TransferState.CANCELLING:
            self._status_tray.show_cancelling(job.source.name)
        elif event.state in {TransferState.CONNECTING, TransferState.TRANSFERRING}:
            self._status_tray.show_connecting(job.source.name)

    def _handle_transfer_progress(self, snapshot: TransferProgress) -> None:
        """Render the newest byte snapshot in the persistent status tray."""

        job = self._jobs.get(snapshot.job_id)
        if job is None or snapshot.job_id != self._active_job_id:
            return
        self._status_tray.show_progress(
            filename=job.source.name,
            transferred_bytes=snapshot.transferred_bytes,
            total_bytes=snapshot.total_bytes,
            percent=snapshot.percent,
            bytes_per_second=snapshot.bytes_per_second,
            eta_seconds=snapshot.eta_seconds,
            is_stalled=snapshot.is_stalled,
        )

    def _handle_transfer_finished(self, event: TransferFinishedEvent) -> None:
        """Finish one page-owned transfer and release the shared start gate."""

        result = event.result
        job = self._jobs.pop(result.job_id, None)
        owner = self._job_owners.pop(result.job_id, None)
        if self._active_job_id == result.job_id:
            self._active_job_id = None
            self._refresh_transfer_gates()
        self._status_tray.show_result(f"state.{result.state.value}")
        if job is None or owner is None:
            return
        if result.is_success:
            owner.record_completed(job)
        elif result.state is TransferState.FAILED:
            owner.show_error(
                localized_backend_message(
                    self._translator,
                    result.message,
                    result.error_kind,
                    context="transfer",
                )
            )

    def _handle_connection_degraded(self, event: ConnectionDegradedEvent) -> None:
        """Close the start gate when a transfer invalidates the tested session."""

        self._is_connection_ready = False
        self._set_connection_health("degraded")
        self._refresh_transfer_gates()
        self._connection_tab.mark_tested(
            False,
            localized_backend_message(
                self._translator,
                event.reason,
                event.error_kind,
                context="connection",
            ),
        )

    def _set_connection_health(self, state: str) -> None:
        """Render one of the three supported connection-health states."""

        style_suffix = {
            "connected": "Connected",
            "disconnected": "Disconnected",
            "degraded": "Degraded",
        }[state]
        self._connection_health.configure(
            text=self._translator.t(f"connection_health.{state}"),
            style=f"Connection{style_suffix}.TLabel",
        )

    def _refresh_transfer_gates(self) -> None:
        """Apply connection readiness and the single active-transfer slot."""

        is_active = self._active_job_id is not None
        for tab in (self._library_update_tab, self._software_update_tab):
            tab.set_connection_ready(self._is_connection_ready)
            tab.set_transfer_active(is_active)

    def _has_pending_work(self) -> bool:
        """Return whether closing would interrupt an active transfer."""

        return self._active_job_id is not None

    def _close_requested(self) -> None:
        """Confirm destructive close, then cancel and clean up before exit."""

        if self._is_shutdown_pending:
            return
        if self._has_pending_work() and not messagebox.askyesno(
            title=self._translator.t("dialogs.close_title"),
            message=self._translator.t("dialogs.close_message"),
            parent=self._tk_root,
        ):
            return
        self._is_shutdown_pending = True
        self._is_connection_ready = False
        self._set_connection_health("disconnected")
        self._refresh_transfer_gates()
        job = self._active_job()
        if job is not None:
            self._status_tray.show_cancelling(job.source.name)
        threading.Thread(
            target=self._shutdown_on_worker,
            name="work-transfer-shutdown",
            daemon=True,
        ).start()

    def _shutdown_on_worker(self) -> None:
        """Wait for remote cleanup away from Tk and publish its outcome."""

        error: BaseException | None = None
        try:
            self._controller.shutdown(timeout=5.0)
        except (RuntimeError, TimeoutError) as caught:
            error = caught
        self._shutdown_results.put(error)


def create_window(
    transfer_controller: TransferControllerLike | None = None,
    translator: TranslatorLike | None = None,
    settings: SettingsLike | None = None,
    update_destinations: UpdateDestinations | None = None,
    mock_tests: tuple[MockTestDefinition, ...] | None = None,
    logo_path: Path | None = None,
) -> tk.Tk:
    """Create the production Ubuntu window with injectable application edges."""

    from work_transfer_app.config import (
        SettingsStore,
        load_mock_tests,
        load_update_destinations,
    )
    from work_transfer_app.localization import Translator
    from work_transfer_app.transfer import TransferController

    settings_store = settings or SettingsStore()
    current_language = settings_store.load_language()
    active_translator = translator or Translator(current_language)
    header_logo = prepare_header_logo(logo_path) if logo_path is not None else None
    destinations = update_destinations or load_update_destinations()
    configured_tests = mock_tests if mock_tests is not None else load_mock_tests()
    owns_controller = transfer_controller is None
    controller = transfer_controller
    root: tk.Tk | None = None

    try:
        root = tk.Tk()
        root.title(active_translator.t("app.title"))
        root.geometry("1080x760")
        root.minsize(900, 650)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        configure_styles(root)
        if controller is None:
            controller = cast(TransferControllerLike, TransferController())
        window = WorkTransferWindow(
            root,
            controller,
            active_translator,
            settings_store,
            current_language,
            destinations,
            configured_tests,
            header_logo=header_logo,
        )
        window.focus_set()
        return root
    except BaseException as startup_error:
        if owns_controller and controller is not None:
            try:
                controller.shutdown()
            except (RuntimeError, TimeoutError) as cleanup_error:
                startup_error.add_note(
                    f"Controller cleanup also failed: {cleanup_error!r}"
                )
        if root is not None:
            try:
                root.destroy()
            except tk.TclError as cleanup_error:
                startup_error.add_note(f"Tk cleanup also failed: {cleanup_error!r}")
        raise
