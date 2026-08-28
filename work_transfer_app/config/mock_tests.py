"""Load ordered mock-test definitions used by the demonstration UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from work_transfer_app.config.update_destinations import (
    ConfigLoadError,
    _load_toml,
    _require_exact_keys,
)

_RESOURCE_NAME = "tests.toml"
_TEST_KEYS = frozenset({"id", "name"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_UNSAFE_NAME_CHARACTERS = frozenset({"\0", "\n", "\r"})


@dataclass(frozen=True, slots=True)
class MockTestDefinition:
    """Define one named mock diagnostic in stable configuration order."""

    id: str
    name: str


def load_mock_tests(path: Path | None = None) -> tuple[MockTestDefinition, ...]:
    """Load and validate ordered mock-test definitions from TOML."""

    raw = _load_toml(path, _RESOURCE_NAME)
    _require_exact_keys(raw, {"tests"}, "mock-test configuration")

    tests = raw["tests"]
    if not isinstance(tests, list):
        raise ConfigLoadError("'tests' must use ordered [[tests]] TOML entries.")
    if not tests:
        raise ConfigLoadError("Mock-test configuration must contain at least one test.")

    definitions: list[MockTestDefinition] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(tests, start=1):
        definition = _parse_test_definition(entry, index)
        if definition.id in seen_ids:
            raise ConfigLoadError(f"Mock-test id '{definition.id}' is duplicate.")
        seen_ids.add(definition.id)
        definitions.append(definition)
    return tuple(definitions)


def _parse_test_definition(value: object, index: int) -> MockTestDefinition:
    """Validate and convert one ordered mock-test table."""

    if not isinstance(value, dict):
        raise ConfigLoadError(f"Mock-test entry {index} must be a TOML table.")
    _require_exact_keys(value, _TEST_KEYS, f"mock-test entry {index}")

    test_id = value["id"]
    name = value["name"]
    if not isinstance(test_id, str) or _SAFE_ID.fullmatch(test_id) is None:
        raise ConfigLoadError(
            f"Mock-test entry {index} id must be a safe identifier containing only "
            "letters, digits, '-' or '_'."
        )
    if not isinstance(name, str) or not name.strip():
        raise ConfigLoadError(f"Mock-test entry {index} name must be nonblank.")
    if any(character in name for character in _UNSAFE_NAME_CHARACTERS):
        raise ConfigLoadError(
            f"Mock-test entry {index} name must not contain line breaks or NUL."
        )
    return MockTestDefinition(id=test_id, name=name)
