"""Load the fixed remote destinations used by update transfers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from work_transfer_app.config.toml import (
    ConfigLoadError,
    load_toml,
    require_exact_keys,
)

_RESOURCE_NAME = "updates.toml"
_DESTINATION_KEYS = frozenset({"library_update", "software_update"})
_UNSAFE_PATH_CHARACTERS = frozenset({"\0", "\n", "\r"})


@dataclass(frozen=True, slots=True)
class UpdateDestinations:
    """Define the fixed remote directory for each update workflow."""

    library_update: str
    software_update: str


def load_update_destinations(path: Path | None = None) -> UpdateDestinations:
    """Load and validate update destinations from a TOML file or bundled resource."""

    raw = load_toml(path, _RESOURCE_NAME)
    require_exact_keys(raw, {"destinations"}, "update configuration")

    destinations = raw["destinations"]
    if not isinstance(destinations, dict):
        raise ConfigLoadError("'destinations' must be a TOML table.")
    require_exact_keys(destinations, _DESTINATION_KEYS, "destinations")

    return UpdateDestinations(
        library_update=_normalize_remote_path(
            destinations["library_update"], "library_update"
        ),
        software_update=_normalize_remote_path(
            destinations["software_update"], "software_update"
        ),
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
