"""Feature-local tab components for the desktop shell."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Callable
from functools import partial
from pathlib import Path
from random import Random
from tkinter import filedialog, ttk
from typing import cast

from work_transfer_app import __version__
from work_transfer_app.config import MockTestDefinition
from work_transfer_app.transfer import TransferErrorKind, TransferJob
from work_transfer_app.ui.contracts import SettingsLike, TranslatorLike
from work_transfer_app.ui.messages import localized_backend_message
from work_transfer_app.ui.mock_tests import RandomSource, plan_mock_tests

StartTransfer = Callable[[Path, str], TransferJob]
ScheduleCallback = Callable[[int, Callable[[], None]], object]
TestConnection = Callable[[str, str, int, Path], None]


class UpdateTransferTab(ttk.Frame):
    """Start one fixed-destination update and show successful session history."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        translation_prefix: str,
        remote_directory: str,
        on_start: StartTransfer,
    ) -> None:
        """Build an update workflow with localized copy and a fixed destination."""

        super().__init__(parent, style="Body.TFrame", padding=(22, 20))
        self._translator = translator
        self._translation_prefix = translation_prefix
        self._remote_directory = remote_directory
        self._on_start = on_start
        self._is_connection_ready = False
        self._is_transfer_active = False
        self._source_path: Path | None = None
        self._source_display = tk.StringVar(
            self, value=self._text("source_placeholder")
        )
        self._error = tk.StringVar(self)
        self._completed_job_ids: set[str] = set()
        self._build()

    def _text(self, suffix: str) -> str:
        """Translate one field from this update workflow's catalog namespace."""

        return self._translator.t(f"{self._translation_prefix}.{suffix}")

    def _build(self) -> None:
        """Lay out the file action on the left and session history on the right."""

        self.columnconfigure(0, weight=1, uniform="update-column")
        self.columnconfigure(1, weight=1, uniform="update-column")
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, style="Body.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(
            header,
            text=self._text("heading"),
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=self._text("description"),
            style="Muted.TLabel",
            wraplength=820,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        form = ttk.Frame(self, style="Panel.TFrame", padding=16)
        form.grid(row=2, column=0, sticky="nsew", pady=(18, 0), padx=(0, 8))
        form.columnconfigure(0, weight=1)
        ttk.Label(
            form,
            text=self._text("source_label"),
            style="PanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(
            form,
            textvariable=self._source_display,
            state="readonly",
        ).grid(row=1, column=0, sticky="ew", pady=(12, 8))
        self._browse_button = ttk.Button(
            form,
            text=self._translator.t("common.browse"),
            command=self._choose_source,
        )
        self._browse_button.grid(row=2, column=0, sticky="w")
        self._start_button = ttk.Button(
            form,
            text=self._text("start_transfer"),
            command=self._start_transfer,
            style="Primary.TButton",
            state="disabled",
        )
        self._start_button.grid(row=3, column=0, sticky="w", pady=(22, 0))
        ttk.Label(
            form,
            textvariable=self._error,
            style="Error.TLabel",
            wraplength=380,
        ).grid(row=4, column=0, sticky="w", pady=(12, 0))

        history_panel = ttk.Frame(self, style="Panel.TFrame", padding=16)
        history_panel.grid(row=2, column=1, sticky="nsew", pady=(18, 0), padx=(8, 0))
        history_panel.columnconfigure(0, weight=1)
        history_panel.rowconfigure(1, weight=1)
        ttk.Label(
            history_panel,
            text=self._text("history_title"),
            style="PanelHeading.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self._history = ttk.Treeview(
            history_panel,
            columns=("file", "status"),
            show="headings",
            selectmode="none",
            height=8,
        )
        self._history.heading("file", text=self._text("history_file"))
        self._history.heading("status", text=self._text("history_status"))
        self._history.column("file", minwidth=150, width=235, stretch=True)
        self._history.column("status", minwidth=115, width=125, stretch=False)
        self._history.grid(row=1, column=0, sticky="nsew")
        self._empty_label = ttk.Label(
            history_panel,
            text=self._text("history_empty"),
            style="MutedPanel.TLabel",
            wraplength=340,
        )
        self._empty_label.place(relx=0.5, rely=0.55, anchor="center")

    def set_connection_ready(self, is_ready: bool) -> None:
        """Update the tested-connection gate for this start action."""

        self._is_connection_ready = is_ready
        self._refresh_start_state()

    def set_transfer_active(self, is_active: bool) -> None:
        """Prevent overlapping starts while retaining all other tab interaction."""

        self._is_transfer_active = is_active
        self._refresh_start_state()

    def show_error(self, message: str) -> None:
        """Display a localized non-blocking error beside the start action."""

        self._error.set(message)

    def record_completed(self, job: TransferJob) -> None:
        """Add one successfully completed matching job to session history."""

        if (
            job.id in self._completed_job_ids
            or job.remote_directory != self._remote_directory
        ):
            return
        self._completed_job_ids.add(job.id)
        self._history.insert(
            "",
            "end",
            iid=job.id,
            values=(job.source.name, self._translator.t("state.completed")),
        )
        self._empty_label.place_forget()

    def _choose_source(self) -> None:
        """Select one local update file without exposing the remote destination."""

        selected = filedialog.askopenfilename(
            parent=self,
            title=self._text("choose_file"),
        )
        if selected:
            self._source_path = Path(selected).expanduser().resolve()
            self._source_display.set(str(self._source_path))
            self._error.set("")

    def _start_transfer(self) -> None:
        """Validate the selected source and delegate one immediate transfer."""

        self._error.set("")
        if not self._is_connection_ready:
            self._error.set(self._text("connection_required"))
            return
        if self._is_transfer_active:
            self._error.set(self._translator.t("errors.transfer_active"))
            return

        source = self._source_path
        if source is None:
            self._error.set(self._text("source_required"))
            return
        if not source.is_file():
            self._error.set(self._text("source_missing"))
            return

        try:
            self._on_start(source, self._remote_directory)
        except (OSError, RuntimeError, ValueError) as error:
            self._error.set(
                localized_backend_message(
                    self._translator,
                    str(error),
                    TransferErrorKind.UNKNOWN,
                    context="transfer",
                )
            )
            return
        self._source_path = None
        self._source_display.set(self._text("source_placeholder"))

    def _refresh_start_state(self) -> None:
        """Apply both connection and global active-transfer gates."""

        if self._is_connection_ready and not self._is_transfer_active:
            self._start_button.state(["!disabled"])
        else:
            self._start_button.state(["disabled"])


class TestTab(ttk.Frame):
    """Run configured demonstration tests with independent mock outcomes."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        definitions: tuple[MockTestDefinition, ...],
        *,
        random_source: RandomSource | None = None,
        scheduler: ScheduleCallback | None = None,
    ) -> None:
        """Build test rows with injectable randomness and scheduling boundaries."""

        super().__init__(parent, style="Body.TFrame", padding=(22, 20))
        self._translator = translator
        self._definitions = definitions
        self._random_source = (
            random_source if random_source is not None else cast(RandomSource, Random())
        )
        self._scheduler = scheduler if scheduler is not None else self._schedule
        self._generation = 0
        self._is_running = False
        self._remaining = 0
        self._status_variables: dict[str, tk.StringVar] = {}
        self._status_boxes: dict[str, ttk.Label] = {}
        self._build()

    def _build(self) -> None:
        """Lay out configured test rows and the run action."""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        ttk.Label(
            self,
            text=self._translator.t("test.heading"),
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=self._translator.t("test.description"),
            style="Muted.TLabel",
            wraplength=800,
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))
        self._run_button = ttk.Button(
            self,
            text=self._translator.t("test.run"),
            command=self.run_tests,
            style="Primary.TButton",
        )
        self._run_button.grid(row=2, column=0, sticky="w", pady=(0, 14))

        panel = ttk.Frame(self, style="Panel.TFrame", padding=16)
        panel.grid(row=3, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(0, weight=1)

        surface_color = ttk.Style(self).lookup("PanelContent.TFrame", "background")
        self._test_canvas = tk.Canvas(
            panel,
            background=surface_color,
            borderwidth=0,
            highlightthickness=0,
            takefocus=False,
        )
        scrollbar = ttk.Scrollbar(
            panel,
            orient="vertical",
            command=self._test_canvas.yview,
        )
        self._test_canvas.configure(yscrollcommand=scrollbar.set)
        self._test_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        self._test_rows = ttk.Frame(
            self._test_canvas,
            style="PanelContent.TFrame",
        )
        self._test_rows.columnconfigure(2, weight=1)
        self._test_rows_window = self._test_canvas.create_window(
            (0, 0),
            window=self._test_rows,
            anchor="nw",
        )
        self._test_rows.bind("<Configure>", self._update_test_scroll_region)
        self._test_canvas.bind("<Configure>", self._resize_test_rows)
        if not self._definitions:
            ttk.Label(
                self._test_rows,
                text=self._translator.t("test.no_tests"),
                style="MutedPanel.TLabel",
            ).grid(row=0, column=0, sticky="w")
            self._run_button.state(["disabled"])
            return

        for row, definition in enumerate(self._definitions):
            self._add_test_row(self._test_rows, row, definition)

    def _update_test_scroll_region(self, _event: tk.Event[tk.Misc]) -> None:
        """Keep the vertical viewport bounded to all configured test rows."""

        bounds = self._test_canvas.bbox("all")
        if bounds is not None:
            self._test_canvas.configure(scrollregion=bounds)

    def _resize_test_rows(self, event: tk.Event[tk.Misc]) -> None:
        """Fill the viewport width while allowing the test rows to grow vertically."""

        self._test_canvas.itemconfigure(self._test_rows_window, width=event.width)

    def _add_test_row(
        self,
        parent: ttk.Frame,
        row: int,
        definition: MockTestDefinition,
    ) -> None:
        """Add one named test with a semantic color box and readable status."""

        status_box = ttk.Label(
            parent,
            text=" ",
            width=3,
            style="TestNotRun.TLabel",
        )
        status_box.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=8)
        status_variable = tk.StringVar(self, value=self._translator.t("test.not_run"))
        ttk.Label(
            parent,
            textvariable=status_variable,
            style="Data.TLabel",
            width=12,
        ).grid(row=row, column=1, sticky="w", padx=(0, 18), pady=8)
        ttk.Label(parent, text=definition.name, style="Data.TLabel").grid(
            row=row, column=2, sticky="w", pady=8
        )
        self._status_variables[definition.id] = status_variable
        self._status_boxes[definition.id] = status_box

    def run_tests(self) -> None:
        """Start one generation of independently timed demonstration tests."""

        if self._is_running or not self._definitions:
            return
        self._generation += 1
        generation = self._generation
        self._is_running = True
        self._remaining = len(self._definitions)
        self._run_button.state(["disabled"])
        for definition in self._definitions:
            self._set_test_state(definition.id, "running")

        plans = plan_mock_tests(self._definitions, self._random_source)
        for plan in plans:
            callback = partial(
                self._complete_test,
                generation,
                plan.test.id,
                plan.is_pass,
            )
            self._scheduler(plan.delay_ms, callback)

    def _complete_test(
        self,
        generation: int,
        test_id: str,
        is_pass: bool,
    ) -> None:
        """Apply one result only when it belongs to the active run generation."""

        if generation != self._generation or not self._is_running:
            return
        self._set_test_state(test_id, "pass" if is_pass else "fail")
        self._remaining -= 1
        if self._remaining == 0:
            self._is_running = False
            self._run_button.state(["!disabled"])

    def _set_test_state(self, test_id: str, state: str) -> None:
        """Update one test's visible text and semantic color style together."""

        status_variable = self._status_variables.get(test_id)
        status_box = self._status_boxes.get(test_id)
        if status_variable is None or status_box is None:
            return
        status_variable.set(self._translator.t(f"test.{state}"))
        style_suffix = {
            "not_run": "NotRun",
            "running": "Running",
            "pass": "Pass",
            "fail": "Fail",
        }[state]
        status_box.configure(style=f"Test{style_suffix}.TLabel")

    def _schedule(self, delay_ms: int, callback: Callable[[], None]) -> object:
        """Schedule one completion through the owning Tk event loop."""

        return self.after(delay_ms, callback)


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
