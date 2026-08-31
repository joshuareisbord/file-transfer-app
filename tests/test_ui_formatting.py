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
        """Render key/value sentinels without duplicating language-file copy."""

        self.keys.append(key)
        rendered_values = ",".join(f"{name}={value}" for name, value in values.items())
        suffix = f":{rendered_values}" if rendered_values else ""
        return f"<{key}{suffix}>"


def test_ui_package_exports_shell_factory() -> None:
    """Keep the package entry point stable for the executable launcher."""

    assert callable(create_window)
    assert WorkTransferWindow.__name__ == "WorkTransferWindow"


def test_transfer_measurements_use_localized_units() -> None:
    """Render progress measurements without embedding display strings in code."""

    translator = RecordingTranslator()

    assert format_byte_count(0, translator) == "<units.bytes:value=0>"
    assert format_byte_count(1536, translator) == "<units.kibibytes:value=1.5>"
    assert format_byte_count(3 * 1024**2, translator) == ("<units.mebibytes:value=3.0>")
    assert format_transfer_rate(2 * 1024**2, translator) == (
        "<units.per_second:value=<units.mebibytes:value=2.0>>"
    )

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

    assert format_eta(None, translator) == "<status.eta_calculating>"
    assert format_eta(0, translator, is_stalled=True) == "<status.eta_stalled>"
    assert format_eta(43, translator) == "<units.duration_seconds:value=43>"
    assert format_eta(125, translator) == (
        "<units.duration_minutes:minutes=2,seconds=5>"
    )
    assert format_eta(7320, translator) == ("<units.duration_hours:hours=2,minutes=2>")
