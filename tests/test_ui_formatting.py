from collections.abc import Callable

from work_transfer_app.ui import WorkTransferWindow, create_window
from work_transfer_app.ui.formatting import (
    format_byte_count,
    format_eta,
    format_transfer_rate,
)


class RecordingTranslator:
    """Return deterministic templates while recording localization lookups."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    def t(self, key: str, **values: object) -> str:
        """Render the small catalog used by formatting tests."""

        self.keys.append(key)
        templates: dict[str, Callable[..., str]] = {
            "units.bytes": lambda value: f"{value} B",
            "units.kibibytes": lambda value: f"{value} KiB",
            "units.mebibytes": lambda value: f"{value} MiB",
            "units.gibibytes": lambda value: f"{value} GiB",
            "units.per_second": lambda value: f"{value}/s",
            "status.eta_calculating": lambda: "Calculating...",
            "status.eta_stalled": lambda: "Stalled",
            "units.duration_seconds": lambda value: f"{value}s",
            "units.duration_minutes": lambda minutes, seconds: f"{minutes}m {seconds}s",
            "units.duration_hours": lambda hours, minutes: f"{hours}h {minutes}m",
        }
        return templates[key](**values)


def test_ui_package_exports_shell_factory() -> None:
    """Keep the package entry point stable for the executable launcher."""

    assert callable(create_window)
    assert WorkTransferWindow.__name__ == "WorkTransferWindow"


def test_transfer_measurements_use_localized_units() -> None:
    """Render progress measurements without embedding display strings in code."""

    translator = RecordingTranslator()

    assert format_byte_count(0, translator) == "0 B"
    assert format_byte_count(1536, translator) == "1.5 KiB"
    assert format_byte_count(3 * 1024**2, translator) == "3.0 MiB"
    assert format_transfer_rate(2 * 1024**2, translator) == "2.0 MiB/s"

    assert translator.keys == [
        "units.bytes",
        "units.kibibytes",
        "units.mebibytes",
        "units.mebibytes",
        "units.per_second",
    ]


def test_eta_covers_calculating_stalled_and_elapsed_ranges() -> None:
    """Keep bottom-tray ETA states concise and deterministic."""

    translator = RecordingTranslator()

    assert format_eta(None, translator) == "Calculating..."
    assert format_eta(0, translator, is_stalled=True) == "Stalled"
    assert format_eta(43, translator) == "43s"
    assert format_eta(125, translator) == "2m 5s"
    assert format_eta(7320, translator) == "2h 2m"
