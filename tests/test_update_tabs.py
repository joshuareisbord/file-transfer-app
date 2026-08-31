"""Behavior tests for update-transfer and configured mock-test tabs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from tkinter import ttk

import pytest

from work_transfer_app.config import MockTestDefinition
from work_transfer_app.localization import Translator
from work_transfer_app.transfer import ConnectionConfig, TransferJob
from work_transfer_app.ui.status_tray import TransferStatusTray
from work_transfer_app.ui.styles import configure_styles
from work_transfer_app.ui.tabs import TestTab as MockTestTab
from work_transfer_app.ui.tabs import UpdateTransferTab


class SequenceRandom:
    """Return deterministic mock-test timings and outcomes."""

    def __init__(self) -> None:
        """Prepare values for two consecutive test runs."""

        self._delays = iter((1000, 2000, 3000, 4000))
        self._outcomes = iter((0.20, 0.01, 0.80, 0.90))

    def randint(self, lower: int, upper: int) -> int:
        """Return the next delay while checking the requested bounds."""

        assert (lower, upper) == (1000, 5000)
        return next(self._delays)

    def random(self) -> float:
        """Return the next controlled pass-or-fail sample."""

        return next(self._outcomes)


class RecordingScheduler:
    """Retain scheduled callbacks so tests can complete them immediately."""

    def __init__(self) -> None:
        """Create an empty schedule."""

        self.calls: list[tuple[int, Callable[[], None]]] = []

    def __call__(self, delay_ms: int, callback: Callable[[], None]) -> object:
        """Record one delayed callback and return an opaque handle."""

        self.calls.append((delay_ms, callback))
        return len(self.calls)


@pytest.fixture(scope="module")
def tk_session_root() -> Iterator[tk.Tk]:
    """Provide one Tk interpreter for this module's UI behavior tests."""

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk display unavailable: {error}")
    try:
        yield root
    finally:
        root.destroy()


@pytest.fixture
def tk_root(tk_session_root: tk.Tk) -> Iterator[tk.Tk]:
    """Reset and style the shared Tk root for one isolated test."""

    configure_styles(tk_session_root)
    try:
        yield tk_session_root
    finally:
        for child in tk_session_root.winfo_children():
            child.destroy()
        tk_session_root.update_idletasks()


def _job(source: Path, remote_directory: str, tmp_path: Path) -> TransferJob:
    """Create one immutable job for a tab callback."""

    return TransferJob.create(
        source,
        remote_directory,
        ConnectionConfig(
            host="computer-b",
            username="demo",
            identity_file=tmp_path / "id_ed25519",
            known_hosts=tmp_path / "known_hosts",
        ),
    )


def _label_text(label: ttk.Label) -> str:
    """Return text rendered directly or through a Tk variable."""

    direct_text = str(label.cget("text"))
    variable_name = str(label.cget("textvariable"))
    if direct_text or not variable_name:
        return direct_text
    return str(label.getvar(variable_name))


def test_update_tab_uses_fixed_destination_and_logs_only_completed_files(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start from one selected file without exposing a destination or queue."""

    source = tmp_path / "library.pkg"
    source.write_bytes(b"library update")
    started: list[tuple[Path, str]] = []
    translator = Translator("en")

    def start_transfer(selected: Path, remote_directory: str) -> TransferJob:
        """Record the start boundary and return the controller job."""

        started.append((selected, remote_directory))
        return _job(selected, remote_directory, tmp_path)

    monkeypatch.setattr(
        "work_transfer_app.ui.tabs.filedialog.askopenfilename",
        lambda **_kwargs: str(source),
    )
    tab = UpdateTransferTab(
        tk_root,
        translator,
        translation_prefix="library_update",
        remote_directory="~/library-updates",
        on_start=start_transfer,
    )
    tab.pack(fill="both", expand=True)
    tab.set_connection_ready(True)
    tab._browse_button.invoke()
    tab._start_button.invoke()

    assert started == [(source.resolve(), "~/library-updates")]
    assert tab._history.cget("columns") == ("file", "status")
    assert tab._history.get_children() == ()

    job = _job(source, "~/library-updates", tmp_path)
    tab.record_completed(job)

    assert len(tab._history.get_children()) == 1
    row = tab._history.item(tab._history.get_children()[0], "values")
    assert row == ("library.pkg", translator.t("state.completed"))


def test_update_tab_gates_start_on_connection_and_active_transfer(
    tk_root: tk.Tk,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable starts until connected and whenever either update is active."""

    source = tmp_path / "software.pkg"
    source.write_bytes(b"software update")
    monkeypatch.setattr(
        "work_transfer_app.ui.tabs.filedialog.askopenfilename",
        lambda **_kwargs: str(source),
    )
    tab = UpdateTransferTab(
        tk_root,
        Translator("en"),
        translation_prefix="software_update",
        remote_directory="~/software-updates",
        on_start=lambda selected, destination: _job(selected, destination, tmp_path),
    )
    tab.pack(fill="both", expand=True)
    tab._browse_button.invoke()

    assert tab._start_button.instate(["disabled"])
    tab.set_connection_ready(True)
    assert tab._start_button.instate(["!disabled"])
    tab.set_transfer_active(True)
    assert tab._start_button.instate(["disabled"])
    tab.set_transfer_active(False)
    assert tab._start_button.instate(["!disabled"])


def test_test_tab_runs_each_definition_independently_and_ignores_old_callbacks(
    tk_root: tk.Tk,
) -> None:
    """Show running then independent results without stale-run mutation."""

    scheduler = RecordingScheduler()
    translator = Translator("en")
    tab = MockTestTab(
        tk_root,
        translator,
        (
            MockTestDefinition("fixture_alpha", "Fixture alpha"),
            MockTestDefinition("fixture_beta", "Fixture beta"),
        ),
        random_source=SequenceRandom(),
        scheduler=scheduler,
    )
    tab.pack(fill="both", expand=True)

    status_box = tab._status_boxes["fixture_alpha"]
    result_label = next(
        child
        for child in status_box.master.winfo_children()
        if isinstance(child, ttk.Label)
        and str(child.cget("textvariable"))
        == str(tab._status_variables["fixture_alpha"])
    )
    name_label = next(
        child
        for child in status_box.master.winfo_children()
        if isinstance(child, ttk.Label) and child.cget("text") == "Fixture alpha"
    )
    assert status_box.grid_info()["column"] == 0
    assert result_label.grid_info()["column"] == 1
    assert name_label.grid_info()["column"] == 2

    assert [value.get() for value in tab._status_variables.values()] == [
        translator.t("test.not_run"),
        translator.t("test.not_run"),
    ]
    tab.run_tests()
    first_run = tuple(scheduler.calls)

    assert [delay for delay, _callback in first_run] == [1000, 2000]
    assert [value.get() for value in tab._status_variables.values()] == [
        translator.t("test.running"),
        translator.t("test.running"),
    ]
    assert tab._run_button.instate(["disabled"])

    first_run[0][1]()
    first_run[1][1]()
    assert [value.get() for value in tab._status_variables.values()] == [
        translator.t("test.pass"),
        translator.t("test.fail"),
    ]
    assert tab._run_button.instate(["!disabled"])

    tab.run_tests()
    assert [value.get() for value in tab._status_variables.values()] == [
        translator.t("test.running"),
        translator.t("test.running"),
    ]
    first_run[0][1]()
    assert [value.get() for value in tab._status_variables.values()] == [
        translator.t("test.running"),
        translator.t("test.running"),
    ]


def test_test_tab_scrolls_to_last_configured_definition(tk_root: tk.Tk) -> None:
    """Keep the final configured test reachable when the list exceeds the view."""

    tk_root.geometry("640x480")
    definitions = tuple(
        MockTestDefinition(f"test-{index}", f"Configured test {index}")
        for index in range(1, 41)
    )
    tab = MockTestTab(tk_root, Translator("en"), definitions)
    tab.pack(fill="both", expand=True)
    tk_root.update_idletasks()

    last_label = next(
        child
        for child in tab._test_rows.winfo_children()
        if isinstance(child, ttk.Label) and child.cget("text") == "Configured test 40"
    )
    canvas = tab._test_canvas
    canvas_bottom = canvas.winfo_rooty() + canvas.winfo_height()
    assert last_label.winfo_rooty() >= canvas_bottom
    assert canvas.yview()[1] < 1.0

    canvas.yview_moveto(1.0)
    tk_root.update_idletasks()

    assert canvas.yview()[1] == pytest.approx(1.0)
    assert last_label.winfo_rooty() >= canvas.winfo_rooty()
    assert last_label.winfo_rooty() + last_label.winfo_height() <= canvas_bottom


def test_status_tray_reports_only_the_single_active_transfer(tk_root: tk.Tk) -> None:
    """Render progress, rate, and ETA without any removed queue metadata."""

    translator = Translator("en")
    tray = TransferStatusTray(tk_root, translator, lambda: None)
    tray.pack(fill="x")
    tray.show_progress(
        filename="update.pkg",
        transferred_bytes=512,
        total_bytes=1024,
        percent=50.0,
        bytes_per_second=256.0,
        eta_seconds=2.0,
        is_stalled=False,
    )
    labels = [
        child
        for frame in tray.winfo_children()
        for child in frame.winfo_children()
        if isinstance(child, ttk.Label)
    ]
    rendered = [_label_text(label) for label in labels]

    assert translator.t("status.filename", filename="update.pkg") in rendered
    assert translator.t("status.progress", percent="50.0") in rendered

    tray.show_result("state.completed")
    assert tray._progress_value.get() == 100.0
    assert tray._rate.get() == ""
    assert tray._eta.get() == ""


def test_selected_notebook_tab_uses_mojave_without_size_expansion(
    tk_root: tk.Tk,
) -> None:
    """Selection changes tab color without changing its dimensions."""

    style = ttk.Style(tk_root)

    assert ("selected", "#E7DBC4") in style.map("TNotebook.Tab", query_opt="background")
    assert style.map("TNotebook.Tab", query_opt="expand") == []
