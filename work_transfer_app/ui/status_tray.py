"""Persistent transfer status tray displayed below every tab."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from work_transfer_app.ui.contracts import TranslatorLike
from work_transfer_app.ui.formatting import (
    format_byte_count,
    format_eta,
    format_transfer_rate,
)


class TransferStatusTray(ttk.Frame):
    """Show active transfer measurements while leaving the body interactive."""

    def __init__(
        self,
        parent: tk.Misc,
        translator: TranslatorLike,
        on_abort: Callable[[], None],
    ) -> None:
        """Build a fixed-height progress tray with an injected abort action."""

        super().__init__(parent, style="StatusTray.TFrame", padding=(18, 12))
        self._translator = translator
        self._on_abort = on_abort
        self._filename = tk.StringVar(self)
        self._state = tk.StringVar(self)
        self._transferred = tk.StringVar(self)
        self._rate = tk.StringVar(self)
        self._eta = tk.StringVar(self)
        self._progress_value = tk.DoubleVar(self, value=0.0)
        self._build()
        self.show_idle()

    def _build(self) -> None:
        """Lay out progress information with stable geometry across states."""

        self.columnconfigure(0, weight=1)
        summary = ttk.Frame(self, style="StatusContent.TFrame")
        summary.grid(row=0, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)
        ttk.Label(
            summary,
            textvariable=self._filename,
            style="StatusFile.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            summary,
            textvariable=self._state,
            style="StatusState.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(14, 0))

        progress_row = ttk.Frame(self, style="StatusContent.TFrame")
        progress_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        progress_row.columnconfigure(0, weight=1)
        self._progress = ttk.Progressbar(
            progress_row,
            mode="determinate",
            maximum=100,
            variable=self._progress_value,
            style="Transfer.Horizontal.TProgressbar",
        )
        self._progress.grid(row=0, column=0, sticky="ew")
        self._abort_button = ttk.Button(
            progress_row,
            text=self._translator.t("common.abort"),
            command=self._abort,
            state="disabled",
            style="Danger.TButton",
        )
        self._abort_button.grid(row=0, column=1, padx=(14, 0))

        metrics = ttk.Frame(self, style="StatusContent.TFrame")
        metrics.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        metrics.columnconfigure(3, weight=1)
        ttk.Label(
            metrics,
            textvariable=self._transferred,
            style="StatusMeta.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            metrics,
            textvariable=self._rate,
            style="StatusMeta.TLabel",
        ).grid(row=0, column=1, sticky="w", padx=(20, 0))
        ttk.Label(
            metrics,
            textvariable=self._eta,
            style="StatusMeta.TLabel",
        ).grid(row=0, column=2, sticky="w", padx=(20, 0))

    def show_idle(self) -> None:
        """Restore the ready state when no transfer is active."""

        self._filename.set(self._translator.t("status.idle"))
        self._state.set("")
        self._transferred.set("")
        self._rate.set("")
        self._eta.set("")
        self._progress_value.set(0.0)
        self._abort_button.state(["disabled"])

    def show_connecting(self, filename: str) -> None:
        """Show the active file while its SSH connection is opening."""

        self._filename.set(self._translator.t("status.filename", filename=filename))
        self._state.set(self._translator.t("state.connecting"))
        self._transferred.set("")
        self._rate.set("")
        self._eta.set(
            self._translator.t(
                "status.eta",
                eta=self._translator.t("status.eta_calculating"),
            )
        )
        self._progress_value.set(0.0)
        self._abort_button.state(["!disabled"])

    def show_progress(
        self,
        *,
        filename: str,
        transferred_bytes: int,
        total_bytes: int,
        percent: float,
        bytes_per_second: float | None,
        eta_seconds: float | None,
        is_stalled: bool,
    ) -> None:
        """Display a bounded snapshot from the background transfer worker."""

        safe_percent = min(100.0, max(0.0, percent))
        self._filename.set(self._translator.t("status.filename", filename=filename))
        self._state.set(
            self._translator.t("status.progress", percent=f"{safe_percent:.1f}")
        )
        self._transferred.set(
            self._translator.t(
                "status.transferred",
                sent=format_byte_count(transferred_bytes, self._translator),
                total=format_byte_count(total_bytes, self._translator),
            )
        )
        self._rate.set(format_transfer_rate(bytes_per_second or 0.0, self._translator))
        self._eta.set(
            self._translator.t(
                "status.eta",
                eta=format_eta(
                    eta_seconds,
                    self._translator,
                    is_stalled=is_stalled,
                ),
            )
        )
        self._progress_value.set(safe_percent)
        self._abort_button.state(["!disabled"])

    def show_cancelling(self, filename: str) -> None:
        """Disable repeated cancellation while cleanup is in progress."""

        self._filename.set(self._translator.t("status.filename", filename=filename))
        self._state.set(self._translator.t("state.cancelling"))
        self._abort_button.state(["disabled"])

    def show_result(self, state_key: str) -> None:
        """Show a terminal state until the next worker event arrives."""

        self._state.set(self._translator.t(state_key))
        self._rate.set("")
        self._eta.set("")
        if state_key == "state.completed":
            self._progress_value.set(100.0)
        self._abort_button.state(["disabled"])

    def _abort(self) -> None:
        """Request cancellation without waiting on worker shutdown."""

        self._abort_button.state(["disabled"])
        self._on_abort()
