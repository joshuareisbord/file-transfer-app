import json
from pathlib import Path

from work_transfer_app.localization import Translator, discover_languages


def _write_catalog(
    directory: Path, code: str, name: str, strings: dict[str, str]
) -> None:
    """Write a language catalog fixture."""

    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{code}.json").write_text(
        json.dumps({"metadata": {"code": code, "name": name}, "strings": strings}),
        encoding="utf-8",
    )


def test_bundled_english_catalog_contains_required_keys() -> None:
    """Keep application lookups present without pinning translated wording."""

    catalog_path = (
        Path(__file__).parents[1]
        / "work_transfer_app"
        / "localization"
        / "languages"
        / "en.json"
    )
    strings = json.loads(catalog_path.read_text(encoding="utf-8"))["strings"]
    required_keys = {
        "app.title",
        "tabs.library_update",
        "tabs.software_update",
        "tabs.test",
        "tabs.connection",
        "tabs.settings",
        "library_update.source_label",
        "library_update.start_transfer",
        "software_update.source_label",
        "software_update.start_transfer",
        "connection_health.connected",
        "connection_health.disconnected",
        "connection_health.degraded",
        "test.not_run",
        "test.pass",
        "test.fail",
        "units.mebibytes",
        "units.per_second",
        "units.duration_minutes",
        "status.eta_calculating",
        "status.eta_stalled",
        "settings.build_packaged",
        "settings.build_development",
        "settings.localization_warning",
        "warnings.catalog_directory_error",
        "warnings.settings_invalid",
        "warnings.placeholder_mismatch",
        "warnings.missing_translation",
        "warnings.language_not_found",
        "warnings.format_error",
        "warnings.invalid_catalog",
        "warnings.missing_key",
        "errors.settings_save_failed",
        "errors.connection_failed",
        "errors.source_file_missing",
        "errors.remote_file_exists",
        "errors.identity_file_missing",
        "errors.known_hosts_missing",
        "errors.unexpected",
        "errors.transfer_active",
        "errors.remote_directory_invalid",
    }

    for key in required_keys:
        assert key in strings

    translator = Translator()
    assert {language.code for language in translator.languages} == {"en"}
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


def test_catalog_and_missing_key_warnings_are_structured(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, "en", "English", {"status": "Ready"})
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")

    translator = Translator(language_directory=tmp_path)
    assert translator.t("missing") == "missing"

    assert [
        (warning.code, warning.translation_key, warning.key)
        for warning in translator.warnings
    ] == [
        ("invalid_catalog", "warnings.invalid_catalog", None),
        ("missing_key", "warnings.missing_key", "missing"),
    ]
