from pathlib import Path

import pytest

from work_transfer_app.__main__ import main


def test_self_check_loads_transport_language_and_application_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The packaged readiness check covers its runtime dependencies."""

    exit_code = main(["--self-check"])

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "work-transfer: ready (SCP transport, language, branding, and application "
        "config resources loaded)\n"
    )


def test_main_forwards_optional_logo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass the user-selected branding file into the window factory."""

    logo_path = tmp_path / "brand.svg"
    captured: list[Path | None] = []
    mainloop_called: list[bool] = []

    class FakeWindow:
        """Record that the generated application entered its event loop."""

        def mainloop(self) -> None:
            """Record the event-loop call without creating Tk."""

            mainloop_called.append(True)

    def fake_create_window(*, logo_path: Path | None = None) -> FakeWindow:
        """Capture the logo argument and return a non-graphical window."""

        captured.append(logo_path)
        return FakeWindow()

    monkeypatch.setattr("work_transfer_app.ui.create_window", fake_create_window)

    exit_code = main(["--logo", str(logo_path)])

    assert exit_code == 0
    assert captured == [logo_path]
    assert mainloop_called == [True]
