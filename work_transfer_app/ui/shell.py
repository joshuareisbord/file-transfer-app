"""Application shell coordinating tabs with background transfer events."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import cast

from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionTestedEvent,
    ConnectionTestResult,
    JobQueuedEvent,
    JobRemovedEvent,
    QueuePausedEvent,
    QueueResumedEvent,
    TransferErrorKind,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferProgressEvent,
    TransferResult,
    TransferStateEvent,
)
from work_transfer_app.ui.contracts import (
    SettingsLike,
    TransferControllerLike,
    TranslatorLike,
)
from work_transfer_app.ui.messages import localized_backend_message
from work_transfer_app.ui.status_tray import TransferStatusTray
from work_transfer_app.ui.styles import configure_styles
from work_transfer_app.ui.tabs import (
    ConnectionTab,
    QueueItemView,
    SettingsTab,
    TransferTab,
)

_EVENT_POLL_MS = 250
_TERMINAL_STATES = {"completed", "aborted", "failed"}


class WorkTransferWindow(ttk.Frame):
    """Coordinate a fixed tabbed shell with a persistent status tray."""

    def __init__(
        self,
        root: tk.Tk,
        controller: TransferControllerLike,
        translator: TranslatorLike,
        settings: SettingsLike,
        current_language: str,
    ) -> None:
        """Build the UI and begin polling its background event boundary."""

        super().__init__(root, style="Body.TFrame")
        self._tk_root = root
        self._controller = controller
        self._translator = translator
        self._jobs: dict[str, Path] = {}
        self._job_states: dict[str, str] = {}
        self._active_job_id: str | None = None
        self._is_queue_paused = False
        self._operation_results: queue.Queue[tuple[str, bool]] = queue.Queue()
        self._event_poll_id: str | None = None
        self._is_closing = False
        self._build(settings, current_language)
        self._bind_keyboard_navigation()
        self._tk_root.protocol("WM_DELETE_WINDOW", self._close_requested)
        self._schedule_event_poll()

    def _build(self, settings: SettingsLike, current_language: str) -> None:
        """Lay out the fixed header, tab body, and transfer status tray."""

        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 13))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text=self._translator.t("app.title"),
            style="AppTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=self._translator.t("app.subtitle"),
            style="AppSubtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self._notebook = ttk.Notebook(self, takefocus=True)
        self._notebook.grid(row=1, column=0, sticky="nsew")
        self._transfer_tab = TransferTab(
            self._notebook,
            self._translator,
            self._add_transfer,
            self._remove_transfer,
        )
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
        self._notebook.add(self._transfer_tab, text=self._translator.t("tabs.transfer"))
        self._notebook.add(
            self._connection_tab, text=self._translator.t("tabs.connection")
        )
        self._notebook.add(self._settings_tab, text=self._translator.t("tabs.settings"))
        self._notebook.enable_traversal()

        self._status_tray = TransferStatusTray(
            self,
            self._translator,
            self._abort_transfer,
        )
        self._status_tray.grid(row=2, column=0, sticky="ew")

    def _bind_keyboard_navigation(self) -> None:
        """Provide stable shortcuts for switching the three primary tabs."""

        self._tk_root.bind("<Control-Key-1>", self._select_transfer_tab)
        self._tk_root.bind("<Control-Key-2>", self._select_connection_tab)
        self._tk_root.bind("<Control-Key-3>", self._select_settings_tab)

    def _select_transfer_tab(self, _event: tk.Event[tk.Misc]) -> str:
        """Select the transfer tab from its keyboard shortcut."""

        self._notebook.select(0)
        return "break"

    def _select_connection_tab(self, _event: tk.Event[tk.Misc]) -> str:
        """Select the connection tab from its keyboard shortcut."""

        self._notebook.select(1)
        return "break"

    def _select_settings_tab(self, _event: tk.Event[tk.Misc]) -> str:
        """Select the settings tab from its keyboard shortcut."""

        self._notebook.select(2)
        return "break"

    def _add_transfer(self, source: Path, remote_directory: str) -> QueueItemView:
        """Enqueue one transfer and return its immediate row representation."""

        size = source.stat().st_size
        job = self._controller.enqueue(source, remote_directory)
        self._jobs[job.id] = job.source
        self._job_states[job.id] = "queued"
        return QueueItemView(
            job_id=job.id,
            source=job.source,
            remote_directory=job.remote_directory,
            size=size,
        )

    def _remove_transfer(self, job_id: str) -> None:
        """Request removal without blocking the Tk thread on controller I/O."""

        # Controller control calls can wait for its asyncio loop; keep that wait off Tk.
        threading.Thread(
            target=self._remove_on_worker,
            args=(job_id,),
            name="work-transfer-remove",
            daemon=True,
        ).start()

    def _remove_on_worker(self, job_id: str) -> None:
        """Wait for controller removal away from Tk and publish its outcome."""

        try:
            was_removed = self._controller.remove(job_id)
        except (RuntimeError, TimeoutError):
            was_removed = False
        self._operation_results.put(("remove", was_removed))

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
        """Close the UI gate after session connection fields are edited."""

        self._controller.invalidate_connection()
        self._transfer_tab.set_connection_ready(False)

    def _abort_transfer(self) -> None:
        """Request cancellation without blocking the Tk event loop."""

        if self._active_job_id is not None:
            source = self._jobs.get(self._active_job_id)
            if source is not None:
                self._status_tray.show_cancelling(source.name, self._queued_count())
        # Cancellation cleanup belongs to the worker loop and may include remote I/O.
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
        self._operation_results.put(("abort", was_aborted))

    def _schedule_event_poll(self) -> None:
        """Poll transfer events at no more than four UI refreshes per second."""

        self._event_poll_id = self._tk_root.after(
            _EVENT_POLL_MS, self._poll_controller_events
        )

    def _poll_controller_events(self) -> None:
        """Drain immutable worker events only from the Tk thread."""

        if self._is_closing:
            return
        # This polling boundary is the only path from worker threads into Tk widgets.
        self._drain_operation_results()
        while True:
            try:
                event = self._controller.events.get_nowait()
            except queue.Empty:
                break
            self._dispatch_event(event)
        self._schedule_event_poll()

    def _drain_operation_results(self) -> None:
        """Apply control-operation results produced outside the Tk thread."""

        while True:
            try:
                operation, was_accepted = self._operation_results.get_nowait()
            except queue.Empty:
                return
            if operation == "remove" and not was_accepted:
                self._transfer_tab.refresh_remove_action()
            elif operation == "abort" and not was_accepted:
                self._restore_active_status()

    def _restore_active_status(self) -> None:
        """Restore active status if a raced cancellation request was rejected."""

        if self._active_job_id is None:
            self._status_tray.show_idle(self._queued_count())
            return
        source = self._jobs.get(self._active_job_id)
        if source is not None:
            self._status_tray.show_connecting(source.name, self._queued_count())

    def _dispatch_event(self, event: object) -> None:
        """Route a controller event to the smallest affected UI component."""

        if isinstance(event, ConnectionTestedEvent):
            self._handle_connection_tested(event.result)
        elif isinstance(event, JobQueuedEvent):
            self._handle_job_queued(event.job)
        elif isinstance(event, JobRemovedEvent):
            self._handle_job_removed(event.job_id)
        elif isinstance(event, TransferStateEvent):
            self._handle_transfer_state(event.job_id, event.state.value)
        elif isinstance(event, TransferProgressEvent):
            self._handle_transfer_progress(event.progress)
        elif isinstance(event, TransferFinishedEvent):
            self._handle_transfer_finished(event.result)
        elif isinstance(event, QueuePausedEvent):
            self._handle_queue_paused(event.reason, event.error_kind)
        elif isinstance(event, QueueResumedEvent):
            self._is_queue_paused = False
            self._transfer_tab.show_error("")

    def _handle_connection_tested(self, result: ConnectionTestResult) -> None:
        """Update connection gating after an asynchronous test completes."""

        if result.is_stale:
            return
        if result.is_success:
            self._connection_tab.mark_tested(True)
            self._transfer_tab.set_connection_ready(True)
            if self._is_queue_paused:
                if result.can_resume_queue:
                    self._request_resume()
                else:
                    self._transfer_tab.show_error(
                        self._translator.t("errors.queue_config_mismatch")
                    )
            return

        message = self._connection_error_text(result.error_kind, result.message)
        self._connection_tab.mark_tested(False, message)
        self._transfer_tab.set_connection_ready(False)

    def _request_resume(self) -> None:
        """Ask the controller to resume without blocking the Tk event loop."""

        threading.Thread(
            target=self._resume_on_worker,
            name="work-transfer-resume",
            daemon=True,
        ).start()

    def _resume_on_worker(self) -> None:
        """Resume paused transfer work without blocking the Tk event loop."""

        try:
            self._controller.resume()
        except (RuntimeError, TimeoutError):
            return

    def _connection_error_text(self, error_kind: TransferErrorKind, detail: str) -> str:
        """Map stable backend error kinds to localized connection feedback."""

        return localized_backend_message(
            self._translator,
            detail,
            error_kind,
            context="connection",
        )

    def _handle_job_queued(self, queued_job: TransferJob) -> None:
        """Reconcile a queued event which was not inserted synchronously."""

        if queued_job.id in self._jobs:
            return
        self._jobs[queued_job.id] = queued_job.source
        self._job_states[queued_job.id] = "queued"
        try:
            size = queued_job.source.stat().st_size
        except OSError:
            size = 0
        self._transfer_tab.add_item(
            QueueItemView(
                queued_job.id,
                queued_job.source,
                queued_job.remote_directory,
                size,
            )
        )

    def _handle_job_removed(self, job_id: str) -> None:
        """Reconcile a controller-side removal with the visible queue."""

        self._jobs.pop(job_id, None)
        self._job_states.pop(job_id, None)
        self._transfer_tab.remove_item(job_id)
        if self._active_job_id is None:
            self._status_tray.show_idle(self._queued_count())
        if self._is_queue_paused:
            # The controller accepts this only after all remaining snapshots match.
            self._request_resume()

    def _handle_transfer_state(self, job_id: str, state: str) -> None:
        """Update queue and bottom tray for a non-terminal state transition."""

        self._job_states[job_id] = state
        self._transfer_tab.update_item_state(job_id, f"state.{state}")
        source = self._jobs.get(job_id)
        if state in {"connecting", "transferring", "cancelling"}:
            self._active_job_id = job_id
        if source is None:
            return
        if state == "cancelling":
            self._status_tray.show_cancelling(source.name, self._queued_count())
        elif state in {"connecting", "transferring"}:
            self._status_tray.show_connecting(source.name, self._queued_count())

    def _handle_transfer_progress(self, snapshot: TransferProgress) -> None:
        """Render the newest byte snapshot in the persistent status tray."""

        job_id = snapshot.job_id
        source = self._jobs.get(job_id)
        if source is None:
            return
        self._active_job_id = job_id
        self._job_states[job_id] = "transferring"
        self._status_tray.show_progress(
            filename=source.name,
            transferred_bytes=snapshot.transferred_bytes,
            total_bytes=snapshot.total_bytes,
            percent=snapshot.percent,
            bytes_per_second=snapshot.bytes_per_second or 0.0,
            eta_seconds=snapshot.eta_seconds,
            is_stalled=snapshot.is_stalled,
            queued_count=self._queued_count(),
        )

    def _handle_transfer_finished(self, completed: TransferResult) -> None:
        """Show a terminal result while allowing the next queued job to begin."""

        job_id = completed.job_id
        state = completed.state.value
        self._job_states[job_id] = state
        self._transfer_tab.update_item_state(job_id, f"state.{state}")
        if self._active_job_id == job_id:
            self._active_job_id = None
        self._status_tray.show_result(f"state.{state}", self._queued_count())
        if state == "failed":
            self._transfer_tab.show_error(
                localized_backend_message(
                    self._translator,
                    completed.message,
                    completed.error_kind,
                    context="transfer",
                )
            )

    def _handle_queue_paused(self, reason: str, error_kind: TransferErrorKind) -> None:
        """Require a new connection test after a connection-wide failure."""

        self._is_queue_paused = True
        reason_text = self._connection_error_text(error_kind, reason)
        message = self._translator.t("errors.queue_paused", detail=reason_text)
        self._connection_tab.mark_tested(False, message)
        self._transfer_tab.set_connection_ready(False)
        self._transfer_tab.show_error(message)

    def _queued_count(self) -> int:
        """Return only waiting items, excluding active and terminal rows."""

        return sum(state == "queued" for state in self._job_states.values())

    def _has_pending_work(self) -> bool:
        """Return whether closing would interrupt queued or active work."""

        return any(state not in _TERMINAL_STATES for state in self._job_states.values())

    def _close_requested(self) -> None:
        """Confirm destructive close, then cancel and clean up before exit."""

        if self._has_pending_work() and not messagebox.askyesno(
            title=self._translator.t("dialogs.close_title"),
            message=self._translator.t("dialogs.close_message"),
            parent=self._tk_root,
        ):
            return
        self._is_closing = True
        if self._event_poll_id is not None:
            self._tk_root.after_cancel(self._event_poll_id)
            self._event_poll_id = None
        self._controller.shutdown(timeout=5.0)
        self._tk_root.destroy()


def create_window(
    transfer_controller: TransferControllerLike | None = None,
    translator: TranslatorLike | None = None,
    settings: SettingsLike | None = None,
) -> tk.Tk:
    """Create the production Ubuntu window with injectable application edges."""

    from work_transfer_app.config import SettingsStore
    from work_transfer_app.localization import Translator
    from work_transfer_app.transfer import TransferQueueController

    settings_store = settings or SettingsStore()
    current_language = settings_store.load_language()
    active_translator = translator or Translator(current_language)
    controller = transfer_controller or cast(
        TransferControllerLike, TransferQueueController()
    )

    root = tk.Tk()
    root.title(active_translator.t("app.title"))
    root.geometry("980x760")
    root.minsize(820, 650)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    configure_styles(root)
    window = WorkTransferWindow(
        root,
        controller,
        active_translator,
        settings_store,
        current_language,
    )
    window.focus_set()
    return root
