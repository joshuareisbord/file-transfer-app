import json
from pathlib import Path

from work_transfer_app.localization import (
    LocalizationWarning,
    Translator,
    discover_languages,
)


def _write_catalog(
    directory: Path, code: str, name: str, strings: dict[str, str]
) -> None:
    """Write a language catalog fixture."""

    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{code}.json").write_text(
        json.dumps({"metadata": {"code": code, "name": name}, "strings": strings}),
        encoding="utf-8",
    )


def _render_warning(warning: LocalizationWarning) -> str:
    """Render a structured warning through the bundled English translator."""

    return Translator().t(warning.translation_key, **warning.values)


def test_bundled_english_catalog_exposes_metadata_and_formats_ui_text() -> None:
    translator = Translator()

    assert translator.t("app.title") == "Work Transfer"
    assert [
        translator.t(key)
        for key in (
            "tabs.library_update",
            "tabs.software_update",
            "tabs.test",
            "tabs.connection",
            "tabs.settings",
        )
    ] == ["Library Update", "SW Update", "Test", "Connection", "Settings"]
    assert translator.t("library_update.source_label") == "Library update file"
    assert translator.t("library_update.start_transfer") == "Start library update"
    assert translator.t("software_update.source_label") == "Software update file"
    assert translator.t("software_update.start_transfer") == "Start software update"
    assert translator.t("connection_health.connected") == "Connected"
    assert translator.t("connection_health.disconnected") == "Disconnected"
    assert translator.t("connection_health.degraded") == "Degraded"
    assert translator.t("test.not_run") == "Not run"
    assert translator.t("test.pass") == "Pass"
    assert translator.t("test.fail") == "Fail"
    assert translator.t("units.mebibytes", value="12.5") == "12.5 MiB"
    assert translator.t("units.per_second", value="8 MiB") == "8 MiB/s"
    assert translator.t("units.duration_minutes", minutes=3, seconds=12) == "3m 12s"
    assert translator.t("status.eta_calculating") == "Calculating..."
    assert translator.t("status.eta_stalled") == "Transfer stalled"
    assert translator.t("settings.build_packaged") == "Packaged executable"
    assert translator.t("settings.build_development") == "Development"
    assert translator.t("errors.settings_save_failed", detail="read-only") == (
        "Could not save settings: read-only"
    )
    assert translator.t("errors.connection_failed", detail="timed out") == (
        "Could not connect to the receiver: timed out"
    )
    assert translator.t("settings.localization_warning", detail="fallback") == (
        "Language warning: fallback"
    )
    assert [(language.code, language.name) for language in translator.languages] == [
        ("en", "English")
    ]
    assert translator.warnings == ()


def test_translation_falls_back_per_key_and_rejects_placeholder_drift(
    tmp_path: Path,
) -> None:
    _write_catalog(
        tmp_path,
        "en",
        "English",
        {
            "greeting": "Hello, {name}",
            "status": "Ready",
        },
    )
    _write_catalog(
        tmp_path,
        "de",
        "Deutsch",
        {
            "greeting": "Hallo, {username}",
        },
    )

    translator = Translator("de", language_directory=tmp_path)

    assert translator.t("greeting", name="Ada") == "Hello, Ada"
    assert translator.t("status") == "Ready"
    assert [
        (warning.code, warning.translation_key, warning.key)
        for warning in translator.warnings
    ] == [
        ("placeholder_mismatch", "warnings.placeholder_mismatch", "greeting"),
        ("missing_translation", "warnings.missing_translation", "status"),
    ]
    assert [_render_warning(warning) for warning in translator.warnings] == [
        "Translation 'greeting' has different placeholders; using English.",
        "Language 'de' is missing 'status'; using English.",
    ]
    assert [
        (language.code, language.name) for language in discover_languages(tmp_path)
    ] == [
        ("de", "Deutsch"),
        ("en", "English"),
    ]


def test_missing_selected_language_and_render_arguments_surface_warnings(
    tmp_path: Path,
) -> None:
    _write_catalog(
        tmp_path,
        "en",
        "English",
        {"greeting": "Hello, {name}"},
    )

    translator = Translator("fr", language_directory=tmp_path)

    assert translator.t("greeting") == "Hello, {name}"
    assert [
        (warning.code, warning.translation_key, warning.key)
        for warning in translator.warnings
    ] == [
        ("language_not_found", "warnings.language_not_found", None),
        ("format_error", "warnings.format_error", "greeting"),
    ]
    assert [_render_warning(warning) for warning in translator.warnings] == [
        "Language 'fr' is unavailable; using English.",
        "Could not format translation 'greeting': 'name'",
    ]


def test_catalog_and_missing_key_warnings_are_structured_and_renderable(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "en", "English", {"status": "Ready"})
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")

    translator = Translator(language_directory=tmp_path)
    assert translator.t("missing") == "missing"

    assert [_render_warning(warning) for warning in translator.warnings] == [
        "Ignored language catalog 'broken.json': invalid JSON",
        "Translation key 'missing' does not exist.",
    ]


def test_all_warning_and_transfer_templates_are_renderable() -> None:
    translator = Translator()

    assert (
        translator.t("warnings.catalog_directory_error", detail="permission denied")
        == "Could not read language catalogs: permission denied"
    )
    assert translator.t("warnings.settings_invalid") == (
        "Settings file is invalid; using the English language default."
    )
    assert translator.t("errors.source_file_missing") == (
        "The source file changed or disappeared before transfer."
    )
    assert translator.t("errors.remote_file_exists") == (
        "A file with this name already exists in the remote update directory."
    )
    assert translator.t("errors.identity_file_missing") == (
        "The selected private key no longer exists."
    )
    assert translator.t("errors.known_hosts_missing") == (
        "The known_hosts file does not exist."
    )
    assert translator.t("errors.unexpected") == "An unexpected error occurred."
    assert translator.t("errors.transfer_active") == (
        "A file transfer is already active."
    )
    assert translator.t("errors.remote_directory_invalid") == (
        "The configured remote update directory must begin with / or ~/."
    )


def test_catalog_has_no_obsolete_queue_or_destination_ui_copy() -> None:
    """Keep removed queue and destination controls out of the language contract."""

    catalog_path = (
        Path(__file__).parents[1]
        / "work_transfer_app"
        / "localization"
        / "languages"
        / "en.json"
    )
    strings = json.loads(catalog_path.read_text(encoding="utf-8"))["strings"]

    assert not any(key.startswith("transfer.") for key in strings)
    assert not any("queue" in key for key in strings)
    assert not any("queue" in value.casefold() for value in strings.values())
    assert "status.queue_count" not in strings
    assert "validation.destination_required" not in strings
    assert "validation.destination_invalid" not in strings
