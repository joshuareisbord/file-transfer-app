import json
from pathlib import Path

from work_transfer_app.config import SettingsStore, default_settings_path


def test_settings_store_persists_only_the_selected_language(tmp_path: Path) -> None:
    settings_path = tmp_path / "nested" / "settings.json"
    store = SettingsStore(path=settings_path)

    assert store.load_language() == "en"

    store.save_language("de")

    assert store.load_language() == "de"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"language": "de"}
    assert store.warnings == ()


def test_settings_store_recovers_from_invalid_content(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        '{"language": 12, "host": "must-not-load"}', encoding="utf-8"
    )
    store = SettingsStore(path=settings_path)

    assert store.load_language() == "en"
    assert len(store.warnings) == 1
    warning = store.warnings[0]
    assert (warning.code, warning.translation_key, warning.values) == (
        "settings_invalid",
        "warnings.settings_invalid",
        {},
    )


def test_default_settings_path_honors_xdg_config_home(tmp_path: Path) -> None:
    assert default_settings_path({"XDG_CONFIG_HOME": str(tmp_path)}) == (
        tmp_path / "work-transfer" / "settings.json"
    )
