"""Behavior tests for the configurable UI color theme."""

from pathlib import Path

import pytest

from work_transfer_app.ui.theme import ThemeLoadError, load_theme


def test_default_theme_loads_supplied_rgb_palette_and_semantic_roles() -> None:
    """Resolve every configured role from the seven supplied RGB colors."""

    theme = load_theme()

    assert theme.palette == {
        "primary.blue": "#1F3B64",
        "primary.mojave": "#E7DBC4",
        "secondary.black": "#0A0A0A",
        "secondary.white": "#FAFAFA",
        "accent.red": "#BC2026",
        "accent.green": "#4B5126",
        "accent.orange": "#E4592D",
    }
    assert theme.color("header") == "#1F3B64"
    assert theme.color("canvas") == "#E7DBC4"
    assert theme.color("ink") == "#0A0A0A"
    assert theme.color("surface") == "#FAFAFA"
    assert theme.color("danger") == "#BC2026"
    assert theme.color("success") == "#4B5126"
    assert theme.color("active_accent") == "#E4592D"
    assert theme.color("tab_selected") == "#E7DBC4"
    assert theme.color("tab_selected_text") == "#0A0A0A"
    assert theme.color("connection_connected") == "#4B5126"
    assert theme.color("connection_disconnected") == "#BC2026"
    assert theme.color("connection_degraded") == "#E4592D"
    assert theme.color("test_not_run") == "#E7DBC4"
    assert theme.color("test_running") == "#E4592D"
    assert theme.color("test_pass") == "#4B5126"
    assert theme.color("test_fail") == "#BC2026"
    assert set(theme.roles.values()) <= set(theme.palette.values())


def test_theme_rejects_rgb_components_outside_byte_range(tmp_path: Path) -> None:
    """Reject malformed RGB configuration before Tk receives a color value."""

    theme_path = tmp_path / "theme.toml"
    theme_path.write_text(
        """
[palette.primary]
blue = [31, 59, 256]

[roles]
canvas = "primary.blue"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ThemeLoadError, match="primary.blue"):
        load_theme(theme_path)
