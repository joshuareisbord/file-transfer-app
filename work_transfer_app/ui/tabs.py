"""Feature-local tab components for the desktop shell."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, ttk

from work_transfer_app import __version__
from work_transfer_app.transfer import TransferErrorKind
from work_transfer_app.ui.contracts import SettingsLike, TranslatorLike
from work_transfer_app.ui.formatting import format_byte_count
from work_transfer_app.ui.messages import localized_backend_message


@dataclass(frozen=True, slots=True)
class QueueItemView:
    """Contain the display fields for one queued transfer."""

    job_id: str
    source: Path
    remote_directory: str
    size: int


AddTransfer = Callable[[Path, str], QueueItemView]
RemoveTransfer = Callable[[str], None]
TestConnection = Callable[[str, str, int, Path], None]


class TransferTab(ttk.Frame):
    """Collect transfer input and present the session transfer queue."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        on_add: AddTransfer,
        on_remove: RemoveTransfer,
    ) -> None:
        """Build the transfer tab with injected queue operations."""

        super().__init__(parent, style="Body.TFrame", padding=(22, 20))
        self._translator = translator
        self._on_add = on_add
        self._on_remove = on_remove
        self._is_connection_ready = False
        self._waiting_items: set[str] = set()
        self._source = tk.StringVar(self)
        self._destination = tk.StringVar(self)
        self._error = tk.StringVar(self)
        self._empty_message = tk.StringVar(
            self, value=translator.t("transfer.empty_queue")
        )
        self._build()

    def _build(self) -> None:
        """Lay out transfer inputs, queue controls, and inline feedback."""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, style="Body.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            header,
            text=self._translator.t("transfer.heading"),
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=self._translator.t("transfer.description"),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        form = ttk.Frame(self, style="Panel.TFrame", padding=16)
        form.grid(row=1, column=0, sticky="ew", pady=(18, 14))
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text=self._translator.t("transfer.file")).grid(
            row=0, column=0, sticky="w", padx=(0, 14), pady=5
        )
        ttk.Entry(form, textvariable=self._source).grid(
            row=0, column=1, sticky="ew", pady=5
        )
        ttk.Button(
            form,
            text=self._translator.t("common.browse"),
            command=self._choose_source,
        ).grid(row=0, column=2, padx=(8, 0), pady=5)
        ttk.Label(form, text=self._translator.t("transfer.destination")).grid(
            row=1, column=0, sticky="w", padx=(0, 14), pady=5
        )
        destination_entry = ttk.Entry(form, textvariable=self._destination)
        destination_entry.grid(row=1, column=1, sticky="ew", pady=5)
        self._add_button = ttk.Button(
            form,
            text=self._translator.t("transfer.add_queue"),
            command=self._add_to_queue,
            style="Primary.TButton",
        )
        self._add_button.grid(row=1, column=2, padx=(8, 0), pady=5)
        destination_entry.bind("<Return>", self._handle_add_return)
        ttk.Label(
            form,
            textvariable=self._error,
            style="Error.TLabel",
            wraplength=760,
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(5, 0))

        queue_panel = ttk.Frame(self, style="Panel.TFrame", padding=16)
        queue_panel.grid(row=2, column=0, sticky="nsew")
        queue_panel.columnconfigure(0, weight=1)
        queue_panel.rowconfigure(1, weight=1)
        queue_header = ttk.Frame(queue_panel, style="PanelContent.TFrame")
        queue_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        queue_header.columnconfigure(0, weight=1)
        ttk.Label(
            queue_header,
            text=self._translator.t("transfer.queue"),
            style="PanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._remove_button = ttk.Button(
            queue_header,
            text=self._translator.t("transfer.remove_selected"),
            command=self._remove_selected,
            state="disabled",
        )
        self._remove_button.grid(row=0, column=1, sticky="e")

        columns = ("file", "size", "destination", "status")
        self._queue = ttk.Treeview(
            queue_panel,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self._queue.heading("file", text=self._translator.t("transfer.file_name"))
        self._queue.heading("size", text=self._translator.t("transfer.file_size"))
        self._queue.heading(
            "destination", text=self._translator.t("transfer.queue_destination")
        )
        self._queue.heading("status", text=self._translator.t("transfer.queue_status"))
        self._queue.column("file", minwidth=150, width=260, stretch=True)
        self._queue.column("size", minwidth=90, width=110, stretch=False)
        self._queue.column("destination", minwidth=170, width=280, stretch=True)
        self._queue.column("status", minwidth=100, width=125, stretch=False)
        self._queue.grid(row=1, column=0, sticky="nsew")
        self._queue.bind("<<TreeviewSelect>>", self._selection_changed)
        self._empty_label = ttk.Label(
            queue_panel,
            textvariable=self._empty_message,
            style="MutedPanel.TLabel",
        )
        self._empty_label.place(relx=0.5, rely=0.55, anchor="center")

    def set_connection_ready(self, is_ready: bool) -> None:
        """Update the connection gate used before files enter the queue."""

        self._is_connection_ready = is_ready
        if not is_ready:
            self._add_button.state(["disabled"])
        else:
            self._add_button.state(["!disabled"])

    def add_item(self, item: QueueItemView) -> None:
        """Insert a queued transfer into the visible list."""

        self._queue.insert(
            "",
            "end",
            iid=item.job_id,
            values=(
                item.source.name,
                format_byte_count(item.size, self._translator),
                item.remote_directory,
                self._translator.t("state.queued"),
            ),
        )
        self._waiting_items.add(item.job_id)
        self._empty_label.place_forget()

    def update_item_state(self, job_id: str, state_key: str) -> None:
        """Replace the localized state for a queue row when it exists."""

        if not self._queue.exists(job_id):
            return
        values = list(self._queue.item(job_id, "values"))
        values[3] = self._translator.t(state_key)
        self._queue.item(job_id, values=values)
        if state_key != "state.queued":
            self._waiting_items.discard(job_id)
        self._selection_changed()

    def remove_item(self, job_id: str) -> None:
        """Remove one transfer row and restore the empty state if needed."""

        if self._queue.exists(job_id):
            self._queue.delete(job_id)
        self._waiting_items.discard(job_id)
        if not self._queue.get_children():
            self._empty_label.place(relx=0.5, rely=0.55, anchor="center")
        self._selection_changed()

    def has_items(self) -> bool:
        """Return whether the visible session queue has any rows."""

        return bool(self._queue.get_children())

    def show_error(self, message: str) -> None:
        """Display a non-blocking transfer error beside the form."""

        self._error.set(message)

    def refresh_remove_action(self) -> None:
        """Recalculate removal availability after an asynchronous request."""

        self._selection_changed()

    def _choose_source(self) -> None:
        """Ask for one local file without blocking on transfer work."""

        selected = filedialog.askopenfilename(
            parent=self,
            title=self._translator.t("transfer.choose_file"),
        )
        if selected:
            self._source.set(selected)
            self._error.set("")

    def _handle_add_return(self, _event: tk.Event[tk.Misc]) -> str:
        """Add a transfer when Return is pressed in the destination field."""

        self._add_to_queue()
        return "break"

    def _add_to_queue(self) -> None:
        """Validate visible inputs and delegate creation to the controller."""

        self._error.set("")
        if not self._is_connection_ready:
            self._error.set(self._translator.t("transfer.connection_required"))
            return

        source_text = self._source.get().strip()
        if not source_text:
            self._error.set(self._translator.t("validation.source_required"))
            return
        source = Path(source_text).expanduser()
        if not source.is_file():
            self._error.set(self._translator.t("validation.source_missing"))
            return
        remote_directory = self._destination.get().strip()
        if not remote_directory:
            self._error.set(self._translator.t("validation.destination_required"))
            return
        if not remote_directory.startswith(("/", "~/")) or any(
            character in remote_directory for character in ("\x00", "\n", "\r")
        ):
            self._error.set(self._translator.t("validation.destination_invalid"))
            return

        try:
            item = self._on_add(source, remote_directory)
        except (OSError, RuntimeError, ValueError) as error:
            self._error.set(
                localized_backend_message(
                    self._translator,
                    str(error),
                    TransferErrorKind.UNKNOWN,
                    context="queue",
                )
            )
            return
        self.add_item(item)
        self._source.set("")

    def _selection_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        """Enable removal only for a selected waiting transfer."""

        selection = self._queue.selection()
        is_waiting = bool(selection and selection[0] in self._waiting_items)
        if is_waiting:
            self._remove_button.state(["!disabled"])
        else:
            self._remove_button.state(["disabled"])

    def _remove_selected(self) -> None:
        """Remove the selected item when the controller confirms it is waiting."""

        selection = self._queue.selection()
        if not selection:
            return
        job_id = selection[0]
        self._remove_button.state(["disabled"])
        self._on_remove(job_id)


class ConnectionTab(ttk.Frame):
    """Collect session-only SSH connection settings and test them."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        on_test: TestConnection,
        on_invalidated: Callable[[], None],
    ) -> None:
        """Build the connection form with injected connection operations."""

        super().__init__(parent, style="Body.TFrame", padding=(22, 20))
        self._translator = translator
        self._on_test = on_test
        self._on_invalidated = on_invalidated
        self._is_initializing = True
        self._host = tk.StringVar(self)
        self._username = tk.StringVar(self)
        self._port = tk.StringVar(self, value="22")
        self._identity_file = tk.StringVar(self)
        self._status = tk.StringVar(
            self, value=translator.t("connection.status_untested")
        )
        self._build()
        self._bind_invalidation()
        self._is_initializing = False

    def _build(self) -> None:
        """Lay out connection fields and their inline test status."""

        self.columnconfigure(0, weight=1)
        ttk.Label(
            self,
            text=self._translator.t("connection.heading"),
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=self._translator.t("connection.description"),
            style="Muted.TLabel",
            wraplength=800,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        form = ttk.Frame(self, style="Panel.TFrame", padding=18)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self._add_entry(form, 0, "connection.host", self._host)
        self._add_entry(form, 1, "connection.username", self._username)
        self._add_entry(form, 2, "connection.port", self._port, width=10)
        ttk.Label(form, text=self._translator.t("connection.private_key")).grid(
            row=3, column=0, sticky="w", padx=(0, 14), pady=7
        )
        ttk.Entry(form, textvariable=self._identity_file).grid(
            row=3, column=1, sticky="ew", pady=7
        )
        ttk.Button(
            form,
            text=self._translator.t("common.browse"),
            command=self._choose_identity,
        ).grid(row=3, column=2, padx=(8, 0), pady=7)

        actions = ttk.Frame(form, style="PanelContent.TFrame")
        actions.grid(row=4, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Label(
            actions,
            textvariable=self._status,
            style="InlineStatus.TLabel",
            wraplength=560,
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        self._test_button = ttk.Button(
            actions,
            text=self._translator.t("connection.test"),
            command=self._test_connection,
            style="Primary.TButton",
        )
        self._test_button.grid(row=0, column=1, sticky="e")

    def _add_entry(
        self,
        parent: ttk.Frame,
        row: int,
        key: str,
        variable: tk.StringVar,
        width: int | None = None,
    ) -> None:
        """Add one aligned label and entry to the connection form."""

        ttk.Label(parent, text=self._translator.t(key)).grid(
            row=row, column=0, sticky="w", padx=(0, 14), pady=7
        )
        entry = (
            ttk.Entry(parent, textvariable=variable)
            if width is None
            else ttk.Entry(parent, textvariable=variable, width=width)
        )
        entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=7)

    def _bind_invalidation(self) -> None:
        """Invalidate a successful test whenever any connection field changes."""

        for variable in (
            self._host,
            self._username,
            self._port,
            self._identity_file,
        ):
            variable.trace_add("write", self._connection_changed)

    def _connection_changed(self, *_args: str) -> None:
        """Clear the connection gate after a user-visible field changes."""

        if self._is_initializing:
            return
        self._status.set(self._translator.t("connection.status_invalidated"))
        self._on_invalidated()

    def _choose_identity(self) -> None:
        """Ask the user for an SSH private-key file."""

        selected = filedialog.askopenfilename(
            parent=self,
            title=self._translator.t("connection.choose_key"),
        )
        if selected:
            self._identity_file.set(selected)

    def _test_connection(self) -> None:
        """Validate connection fields and start a background connection test."""

        host = self._host.get().strip()
        if not host:
            self.mark_tested(False, self._translator.t("validation.host_required"))
            return
        username = self._username.get().strip()
        if not username:
            self.mark_tested(False, self._translator.t("validation.username_required"))
            return
        try:
            port = int(self._port.get())
        except ValueError:
            self.mark_tested(False, self._translator.t("validation.port_numeric"))
            return
        if not 1 <= port <= 65535:
            self.mark_tested(False, self._translator.t("validation.port_range"))
            return
        identity_text = self._identity_file.get().strip()
        if not identity_text:
            self.mark_tested(False, self._translator.t("validation.key_required"))
            return
        identity_file = Path(identity_text).expanduser()
        if not identity_file.is_file():
            self.mark_tested(False, self._translator.t("validation.key_missing"))
            return

        self.mark_testing()
        try:
            self._on_test(host, username, port, identity_file)
        except (OSError, RuntimeError, ValueError) as error:
            self.mark_tested(
                False,
                localized_backend_message(
                    self._translator,
                    str(error),
                    TransferErrorKind.UNKNOWN,
                    context="connection",
                ),
            )

    def mark_testing(self) -> None:
        """Show the non-blocking in-progress state for a connection test."""

        self._status.set(self._translator.t("connection.status_testing"))
        self._test_button.state(["disabled"])

    def mark_tested(self, is_success: bool, detail: str = "") -> None:
        """Show a completed connection test result and restore its action."""

        self._test_button.state(["!disabled"])
        if is_success:
            self._status.set(self._translator.t("connection.status_tested"))
        elif detail:
            self._status.set(detail)
        else:
            self._status.set(self._translator.t("errors.connection_failed", detail=""))


class SettingsTab(ttk.Frame):
    """Present restart-scoped language selection and build information."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        settings: SettingsLike,
        current_language: str,
    ) -> None:
        """Build settings from the installed localization catalog."""

        super().__init__(parent, style="Body.TFrame", padding=(22, 20))
        self._translator = translator
        self._settings = settings
        self._language_names = {
            language.name: language.code for language in translator.languages
        }
        selected_name = next(
            (
                language.name
                for language in translator.languages
                if language.code == current_language
            ),
            "",
        )
        self._selected_language = tk.StringVar(self, value=selected_name)
        self._restart_notice = tk.StringVar(self)
        self._build()

    def _build(self) -> None:
        """Lay out language controls, warnings, and immutable build details."""

        self.columnconfigure(0, weight=1)
        ttk.Label(
            self,
            text=self._translator.t("settings.heading"),
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=self._translator.t("settings.description"),
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        panel = ttk.Frame(self, style="Panel.TFrame", padding=18)
        panel.grid(row=2, column=0, sticky="ew")
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text=self._translator.t("settings.language")).grid(
            row=0, column=0, sticky="w", padx=(0, 14), pady=7
        )
        language_selector = ttk.Combobox(
            panel,
            state="readonly",
            textvariable=self._selected_language,
            values=tuple(self._language_names),
        )
        language_selector.grid(row=0, column=1, sticky="ew", pady=7)
        language_selector.bind("<<ComboboxSelected>>", self._language_selected)
        ttk.Label(
            panel,
            textvariable=self._restart_notice,
            style="Notice.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(2, 12))

        ttk.Separator(panel).grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)
        ttk.Label(panel, text=self._translator.t("settings.version")).grid(
            row=3, column=0, sticky="w", padx=(0, 14), pady=7
        )
        ttk.Label(panel, text=__version__, style="Data.TLabel").grid(
            row=3, column=1, sticky="w", pady=7
        )
        ttk.Label(panel, text=self._translator.t("settings.build")).grid(
            row=4, column=0, sticky="w", padx=(0, 14), pady=7
        )
        build_key = (
            "settings.build_packaged"
            if getattr(sys, "frozen", False)
            else "settings.build_development"
        )
        ttk.Label(
            panel,
            text=self._translator.t(build_key),
            style="Data.TLabel",
        ).grid(row=4, column=1, sticky="w", pady=7)

        warnings = (*self._translator.warnings, *self._settings.warnings)
        if warnings:
            warning_text = "\n".join(
                self._translator.t(warning.translation_key, **warning.values)
                for warning in warnings
            )
            ttk.Label(
                panel,
                text=warning_text,
                style="Error.TLabel",
                wraplength=700,
            ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

    def _language_selected(self, _event: tk.Event[tk.Misc]) -> None:
        """Persist a new language and explain its restart boundary."""

        language_code = self._language_names.get(self._selected_language.get())
        if language_code is None:
            return
        try:
            self._settings.save_language(language_code)
        except OSError as error:
            self._restart_notice.set(
                self._translator.t("errors.settings_save_failed", detail=str(error))
            )
            return
        self._restart_notice.set(self._translator.t("settings.restart_required"))
