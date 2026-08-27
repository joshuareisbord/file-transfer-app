"""Load and validate the configurable UI color theme."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import IO

_DEFAULT_THEME_FILE = "theme.toml"
_REQUIRED_ROLES = frozenset(
    {
        "active_accent",
        "active_accent_text",
        "border",
        "button_active",
        "button_active_text",
        "canvas",
        "danger",
        "danger_active",
        "danger_active_text",
        "disabled",
        "disabled_text",
        "header",
        "header_muted",
        "header_text",
        "ink",
        "muted",
        "notice",
        "primary_action",
        "primary_action_active",
        "primary_action_text",
        "progress",
        "selection",
        "selection_text",
        "status_ink",
        "status_meta",
        "status_state",
        "status_surface",
        "success",
        "surface",
        "tab_active",
        "tab_active_text",
    }
)


class ThemeLoadError(ValueError):
    """Report an unreadable or invalid color-theme document."""


@dataclass(frozen=True, slots=True)
class ColorTheme:
    """Expose immutable palette colors and resolved semantic roles."""

    palette: Mapping[str, str]
    roles: Mapping[str, str]

    def __post_init__(self) -> None:
        """Copy both mappings into immutable views."""

        object.__setattr__(self, "palette", MappingProxyType(dict(self.palette)))
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))

    def color(self, role: str) -> str:
        """Return the Tk color assigned to a semantic role."""

        try:
            return self.roles[role]
        except KeyError as error:
            raise KeyError(f"Unknown theme role: {role}") from error


def load_theme(path: str | Path | None = None) -> ColorTheme:
    """Load the packaged theme or a theme from an explicit TOML path."""

    try:
        if path is None:
            theme_resource = resources.files("work_transfer_app.ui").joinpath(
                _DEFAULT_THEME_FILE
            )
            with theme_resource.open("rb") as theme_stream:
                document = _load_document(theme_stream)
        else:
            with Path(path).open("rb") as theme_stream:
                document = _load_document(theme_stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        source = _DEFAULT_THEME_FILE if path is None else str(path)
        raise ThemeLoadError(f"Unable to load theme from {source}: {error}") from error

    return _build_theme(document)


def _load_document(theme_stream: IO[bytes]) -> dict[str, object]:
    """Parse one binary TOML stream into a document."""

    return tomllib.load(theme_stream)


def _build_theme(document: Mapping[str, object]) -> ColorTheme:
    """Validate a parsed document and resolve all semantic references."""

    palette_table = _required_table(document, "palette", "theme")
    palette = _parse_palette(palette_table)
    roles_table = _required_table(document, "roles", "theme")
    roles = _parse_roles(roles_table, palette)
    return ColorTheme(palette=palette, roles=roles)


def _required_table(
    document: Mapping[str, object], key: str, context: str
) -> Mapping[str, object]:
    """Return a required TOML table or raise a contextual validation error."""

    value = document.get(key)
    if not isinstance(value, dict):
        raise ThemeLoadError(f"{context}.{key} must be a TOML table")
    return value


def _parse_palette(palette_table: Mapping[str, object]) -> dict[str, str]:
    """Flatten named palette groups and convert RGB triples to Tk hex colors."""

    palette: dict[str, str] = {}
    for group_name, raw_group in palette_table.items():
        if not isinstance(raw_group, dict):
            raise ThemeLoadError(f"palette.{group_name} must be a TOML table")
        for color_name, raw_rgb in raw_group.items():
            qualified_name = f"{group_name}.{color_name}"
            palette[qualified_name] = _rgb_to_hex(qualified_name, raw_rgb)

    if not palette:
        raise ThemeLoadError("palette must define at least one color")
    return palette


def _rgb_to_hex(name: str, raw_rgb: object) -> str:
    """Validate one exact RGB byte triple and convert it to uppercase hex."""

    if not isinstance(raw_rgb, list) or len(raw_rgb) != 3:
        raise ThemeLoadError(
            f"palette.{name} must be exactly three integer RGB values from 0 to 255"
        )
    if not all(
        isinstance(component, int)
        and not isinstance(component, bool)
        and 0 <= component <= 255
        for component in raw_rgb
    ):
        raise ThemeLoadError(
            f"palette.{name} must be exactly three integer RGB values from 0 to 255"
        )

    red, green, blue = raw_rgb
    return f"#{red:02X}{green:02X}{blue:02X}"


def _parse_roles(
    roles_table: Mapping[str, object], palette: Mapping[str, str]
) -> dict[str, str]:
    """Validate required roles and resolve their palette references."""

    missing_roles = sorted(_REQUIRED_ROLES - roles_table.keys())
    if missing_roles:
        missing = ", ".join(missing_roles)
        raise ThemeLoadError(f"roles table is missing required roles: {missing}")

    roles: dict[str, str] = {}
    for role, reference in roles_table.items():
        if not isinstance(reference, str):
            raise ThemeLoadError(f"roles.{role} must reference a palette color")
        try:
            roles[role] = palette[reference]
        except KeyError as error:
            raise ThemeLoadError(
                f"roles.{role} references unknown palette color: {reference}"
            ) from error
    return roles
