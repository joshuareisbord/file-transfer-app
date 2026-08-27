"""Load language catalogs and render localized application text."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from string import Formatter
from typing import Any


@dataclass(frozen=True, slots=True)
class LanguageMetadata:
    """Describe a language catalog available at application startup."""

    code: str
    name: str


@dataclass(frozen=True, slots=True)
class LocalizationWarning:
    """Describe a recoverable localization problem for the Settings UI."""

    code: str
    translation_key: str
    values: Mapping[str, object] = field(default_factory=dict)
    key: str | None = None


@dataclass(frozen=True, slots=True)
class _Catalog:
    """Hold validated metadata and strings from one catalog file."""

    metadata: LanguageMetadata
    strings: dict[str, str]


def discover_languages(
    language_directory: Path | None = None,
) -> tuple[LanguageMetadata, ...]:
    """Return valid language metadata sorted by language code."""

    catalogs, _warnings = _load_catalogs(_catalog_directory(language_directory))
    return tuple(catalog.metadata for _, catalog in sorted(catalogs.items()))


class Translator:
    """Render strings from one startup-selected language with English fallback."""

    def __init__(
        self,
        language_code: str = "en",
        *,
        language_directory: Path | None = None,
    ) -> None:
        """Load catalogs and select an effective language for this process."""

        catalogs, warnings = _load_catalogs(_catalog_directory(language_directory))
        if "en" not in catalogs:
            raise ValueError("The English language catalog is missing or invalid.")

        self._catalogs = catalogs
        self._warnings = warnings
        self._warning_ids = {(warning.code, warning.key) for warning in warnings}
        self._english = catalogs["en"]
        selected = catalogs.get(language_code)

        if selected is None:
            selected = self._english
            self._add_warning(_warning("language_not_found", language=language_code))

        self._selected = selected
        self._invalid_placeholders = self._find_placeholder_mismatches()

    @property
    def language_code(self) -> str:
        """Return the effective language code used by this translator."""

        return self._selected.metadata.code

    @property
    def languages(self) -> tuple[LanguageMetadata, ...]:
        """Return language choices discovered when the translator was created."""

        return tuple(catalog.metadata for _, catalog in sorted(self._catalogs.items()))

    @property
    def warnings(self) -> tuple[LocalizationWarning, ...]:
        """Return recoverable localization warnings accumulated so far."""

        return tuple(self._warnings)

    def t(self, key: str, **kwargs: object) -> str:
        """Translate and format a key without allowing catalog errors to crash the UI."""

        template = self._template_for(key)
        try:
            return template.format(**kwargs)
        except (IndexError, KeyError, ValueError) as error:
            self._add_warning(
                _warning(
                    "format_error",
                    key=key,
                    translation=key,
                    detail=str(error),
                )
            )
            return template

    def _template_for(self, key: str) -> str:
        """Resolve a template from the selected catalog or its English fallback."""

        if key not in self._invalid_placeholders:
            selected_template = self._selected.strings.get(key)
            if selected_template is not None:
                return selected_template

        english_template = self._english.strings.get(key)
        if english_template is None:
            self._add_warning(
                _warning(
                    "missing_key",
                    key=key,
                    translation=key,
                )
            )
            return key

        if self._selected.metadata.code != "en" and key not in self._selected.strings:
            self._add_warning(
                _warning(
                    "missing_translation",
                    key=key,
                    language=self._selected.metadata.code,
                    translation=key,
                )
            )
        return english_template

    def _find_placeholder_mismatches(self) -> frozenset[str]:
        """Find selected-language templates whose placeholders differ from English."""

        if self._selected.metadata.code == "en":
            return frozenset()

        invalid: set[str] = set()
        for key, selected_template in self._selected.strings.items():
            english_template = self._english.strings.get(key)
            if english_template is None:
                continue
            try:
                matches = _placeholders(selected_template) == _placeholders(
                    english_template
                )
            except ValueError:
                matches = False
            if matches:
                continue
            invalid.add(key)
            self._add_warning(
                _warning(
                    "placeholder_mismatch",
                    key=key,
                    translation=key,
                )
            )
        return frozenset(invalid)

    def _add_warning(self, warning: LocalizationWarning) -> None:
        """Record each warning code and key combination only once."""

        warning_id = (warning.code, warning.key)
        if warning_id in self._warning_ids:
            return
        self._warning_ids.add(warning_id)
        self._warnings.append(warning)


def _catalog_directory(language_directory: Path | None) -> Traversable:
    """Resolve an injected catalog directory or the bundled package resources."""

    if language_directory is not None:
        return language_directory
    return resources.files("work_transfer_app.localization").joinpath("languages")


def _load_catalogs(
    directory: Traversable,
) -> tuple[dict[str, _Catalog], list[LocalizationWarning]]:
    """Load valid JSON catalogs and return warnings for files which were skipped."""

    catalogs: dict[str, _Catalog] = {}
    warnings: list[LocalizationWarning] = []
    try:
        files = sorted(
            (
                child
                for child in directory.iterdir()
                if child.is_file() and child.name.endswith(".json")
            ),
            key=lambda child: child.name,
        )
    except OSError as error:
        warnings.append(_warning("catalog_directory_error", detail=str(error)))
        return catalogs, warnings

    for catalog_file in files:
        try:
            catalog = _parse_catalog(catalog_file)
        except (OSError, TypeError, UnicodeError, ValueError) as error:
            warnings.append(
                _warning(
                    "invalid_catalog",
                    filename=catalog_file.name,
                    detail=str(error),
                )
            )
            continue
        catalogs[catalog.metadata.code] = catalog
    return catalogs, warnings


def _parse_catalog(catalog_file: Traversable) -> _Catalog:
    """Parse and validate one JSON language catalog."""

    try:
        raw: Any = json.loads(catalog_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid JSON") from error

    if not isinstance(raw, dict):
        raise TypeError("catalog root must be an object")
    metadata = raw.get("metadata")
    strings = raw.get("strings")
    if not isinstance(metadata, dict) or not isinstance(strings, dict):
        raise TypeError("catalog must contain metadata and strings objects")

    code = metadata.get("code")
    name = metadata.get("name")
    if not isinstance(code, str) or not code or not isinstance(name, str) or not name:
        raise ValueError("catalog metadata requires non-empty code and name strings")
    if catalog_file.name != f"{code}.json":
        raise ValueError("metadata code must match the catalog filename")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in strings.items()
    ):
        raise ValueError("translation keys and values must be strings")

    typed_strings = {str(key): str(value) for key, value in strings.items()}
    for key, template in typed_strings.items():
        try:
            _placeholders(template)
        except ValueError as error:
            raise ValueError(f"translation '{key}' has invalid placeholders") from error
    return _Catalog(LanguageMetadata(code=code, name=name), typed_strings)


def _placeholders(template: str) -> frozenset[str]:
    """Extract named formatting placeholders from a translation template."""

    return frozenset(
        field_name
        for _literal, field_name, _format_spec, _conversion in Formatter().parse(
            template
        )
        if field_name is not None
    )


def _warning(
    code: str,
    *,
    key: str | None = None,
    **values: object,
) -> LocalizationWarning:
    """Create a warning which references a stable localized message template."""

    return LocalizationWarning(
        code=code,
        translation_key=f"warnings.{code}",
        values=values,
        key=key,
    )
