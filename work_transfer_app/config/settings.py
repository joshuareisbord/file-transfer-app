"""Persist the small set of user-level application settings."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from work_transfer_app.localization import LocalizationWarning

_DEFAULT_LANGUAGE = "en"
_LANGUAGE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def default_settings_path(
    environ: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> Path:
    """Return the XDG-compatible settings path for the current user."""

    environment = os.environ if environ is None else environ
    xdg_config_home = environment.get("XDG_CONFIG_HOME")
    config_home = (
        Path(xdg_config_home).expanduser()
        if xdg_config_home
        else (Path.home() if home is None else home) / ".config"
    )
    return config_home / "work-transfer" / "settings.json"


class SettingsStore:
    """Load and save only the startup-selected language preference."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Create a settings store with an optional injected path for tests."""

        self.path = path if path is not None else default_settings_path(environ)
        self._warnings: list[LocalizationWarning] = []

    @property
    def warnings(self) -> tuple[LocalizationWarning, ...]:
        """Return warnings from the most recent load or save operation."""

        return tuple(self._warnings)

    def load_language(self) -> str:
        """Load the language code or return English for absent or invalid settings."""

        self._warnings.clear()
        if not self.path.exists():
            return _DEFAULT_LANGUAGE
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            self._warnings.append(_invalid_settings_warning())
            return _DEFAULT_LANGUAGE

        if not isinstance(raw, dict) or not _is_language_code(raw.get("language")):
            self._warnings.append(_invalid_settings_warning())
            return _DEFAULT_LANGUAGE
        return raw["language"]

    def save_language(self, language_code: str) -> None:
        """Atomically persist only a validated selected language code."""

        if not _is_language_code(language_code):
            raise ValueError(
                "Language code must contain only letters, digits, '-' or '_'."
            )

        self._warnings.clear()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"language": language_code}, indent=2) + "\n",
            encoding="utf-8",
        )
        # Replacement keeps a partially written settings file from surviving a crash.
        temporary_path.replace(self.path)


def _is_language_code(value: object) -> bool:
    """Return whether a value is a safe, non-empty language identifier."""

    return isinstance(value, str) and _LANGUAGE_CODE.fullmatch(value) is not None


def _invalid_settings_warning() -> LocalizationWarning:
    """Return the localized warning reference used for invalid settings data."""

    return LocalizationWarning(
        code="settings_invalid",
        translation_key="warnings.settings_invalid",
    )
