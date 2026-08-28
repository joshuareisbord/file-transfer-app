"""Provide shared strict TOML-loading helpers for application configuration."""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path


class ConfigLoadError(ValueError):
    """Report an unreadable or invalid bundled application configuration."""


def load_toml(path: Path | None, resource_name: str) -> dict[str, object]:
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


def require_exact_keys(
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
