"""Load the fixed remote destinations used by update transfers."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath

_RESOURCE_NAME = "updates.toml"
_DESTINATION_KEYS = frozenset({"library_update", "software_update"})
_UNSAFE_PATH_CHARACTERS = frozenset({"\0", "\n", "\r"})


class ConfigLoadError(ValueError):
    """Report an unreadable or invalid bundled application configuration."""


@dataclass(frozen=True, slots=True)
class UpdateDestinations:
    """Define the fixed remote directory for each update workflow."""

    library_update: str
    software_update: str


def load_update_destinations(path: Path | None = None) -> UpdateDestinations:
    """Load and validate update destinations from a TOML file or bundled resource."""

    raw = _load_toml(path, _RESOURCE_NAME)
    _require_exact_keys(raw, {"destinations"}, "update configuration")

    destinations = raw["destinations"]
    if not isinstance(destinations, dict):
        raise ConfigLoadError("'destinations' must be a TOML table.")
    _require_exact_keys(destinations, _DESTINATION_KEYS, "destinations")

    return UpdateDestinations(
        library_update=_normalize_remote_path(
            destinations["library_update"], "library_update"
        ),
        software_update=_normalize_remote_path(
            destinations["software_update"], "software_update"
        ),
    )


def _load_toml(path: Path | None, resource_name: str) -> dict[str, object]:
    """Read one TOML document from an injected path or this package's resources."""

    source = str(path) if path is not None else f"bundled {resource_name}"
    try:
        content = (
            path.read_bytes()
            if path is not None
            else resources.files(__package__).joinpath(resource_name).read_bytes()
        )
    except OSError as error:
        raise ConfigLoadError(f"Unable to read {source}: {error}") from error

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigLoadError(f"Unable to decode {source} as UTF-8.") from error

    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigLoadError(f"Invalid TOML in {source}: {error}") from error


def _require_exact_keys(
    table: dict[str, object],
    required_keys: set[str] | frozenset[str],
    context: str,
) -> None:
    """Reject missing and unexpected keys in a strict configuration table."""

    actual_keys = set(table)
    missing_keys = sorted(required_keys - actual_keys)
    unexpected_keys = sorted(actual_keys - required_keys)
    if missing_keys:
        raise ConfigLoadError(
            f"{context} is missing required key(s): {', '.join(missing_keys)}."
        )
    if unexpected_keys:
        raise ConfigLoadError(
            f"{context} contains unexpected key(s): {', '.join(unexpected_keys)}."
        )


def _normalize_remote_path(value: object, field_name: str) -> str:
    """Validate and normalize one absolute or home-relative remote POSIX path."""

    if not isinstance(value, str) or not value.strip():
        raise ConfigLoadError(f"'{field_name}' must be a nonblank string.")
    if any(character in value for character in _UNSAFE_PATH_CHARACTERS):
        raise ConfigLoadError(
            f"'{field_name}' must not contain NUL, line-feed, or carriage-return."
        )

    is_home_relative = value.startswith("~/")
    path_text = value[2:] if is_home_relative else value
    remote_path = PurePosixPath(path_text)

    if not is_home_relative and not remote_path.is_absolute():
        raise ConfigLoadError(
            f"'{field_name}' must be an absolute POSIX path or start with '~/'."
        )
    if is_home_relative and remote_path.is_absolute():
        raise ConfigLoadError(f"'{field_name}' contains an invalid '~/' path.")
    if ".." in remote_path.parts:
        raise ConfigLoadError(f"'{field_name}' must not contain '..'.")

    normalized = remote_path.as_posix()
    if is_home_relative:
        return "~/" if normalized == "." else f"~/{normalized}"
    return normalized
