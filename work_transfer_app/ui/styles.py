"""Light-only industrial visual system for the Tk interface."""

from __future__ import annotations

import tkinter as tk
from tkinter import font, ttk

from work_transfer_app.ui.theme import ColorTheme, load_theme


def configure_styles(root: tk.Tk, theme: ColorTheme | None = None) -> None:
    """Configure a square, high-contrast visual system for the application."""

    active_theme = theme if theme is not None else load_theme()
    color = active_theme.color

    root.configure(background=color("canvas"))
    _configure_fonts(root)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("TFrame", background=color("canvas"))
    style.configure("Body.TFrame", background=color("canvas"))
    style.configure(
        "Panel.TFrame",
        background=color("surface"),
        bordercolor=color("border"),
        borderwidth=1,
        relief="solid",
    )
    style.configure("PanelContent.TFrame", background=color("surface"), borderwidth=0)
    style.configure(
        "Header.TFrame",
        background=color("header"),
        bordercolor=color("border"),
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "HeaderContent.TFrame",
        background=color("header"),
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "StatusTray.TFrame",
        background=color("status_surface"),
        bordercolor=color("border"),
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "StatusContent.TFrame", background=color("status_surface"), borderwidth=0
    )

    style.configure("TLabel", background=color("surface"), foreground=color("ink"))
    style.configure(
        "AppTitle.TLabel",
        background=color("header"),
        foreground=color("header_text"),
        font=("DejaVu Sans", 16, "bold"),
    )
    style.configure(
        "AppSubtitle.TLabel",
        background=color("header"),
        foreground=color("header_muted"),
    )
    style.configure(
        "SectionTitle.TLabel",
        background=color("canvas"),
        foreground=color("ink"),
        font=("DejaVu Sans", 15, "bold"),
    )
    style.configure(
        "Muted.TLabel", background=color("canvas"), foreground=color("muted")
    )
    style.configure(
        "PanelHeading.TLabel",
        background=color("surface"),
        foreground=color("ink"),
        font=("DejaVu Sans", 11, "bold"),
    )
    style.configure(
        "MutedPanel.TLabel",
        background=color("surface"),
        foreground=color("muted"),
    )
    style.configure(
        "Error.TLabel", background=color("surface"), foreground=color("danger")
    )
    style.configure(
        "Notice.TLabel", background=color("surface"), foreground=color("notice")
    )
    style.configure("Data.TLabel", background=color("surface"), foreground=color("ink"))
    style.configure(
        "InlineStatus.TLabel",
        background=color("surface"),
        foreground=color("muted"),
    )
    style.configure(
        "StatusFile.TLabel",
        background=color("status_surface"),
        foreground=color("status_ink"),
        font=("DejaVu Sans", 10, "bold"),
    )
    style.configure(
        "StatusState.TLabel",
        background=color("status_surface"),
        foreground=color("status_state"),
    )
    style.configure(
        "StatusMeta.TLabel",
        background=color("status_surface"),
        foreground=color("status_meta"),
    )
    for style_name, background_role, foreground_role in (
        (
            "ConnectionConnected.TLabel",
            "connection_connected",
            "connection_connected_text",
        ),
        (
            "ConnectionDisconnected.TLabel",
            "connection_disconnected",
            "connection_disconnected_text",
        ),
        (
            "ConnectionDegraded.TLabel",
            "connection_degraded",
            "connection_degraded_text",
        ),
    ):
        style.configure(
            style_name,
            background=color(background_role),
            foreground=color(foreground_role),
            bordercolor=color("border"),
            borderwidth=1,
            relief="solid",
            padding=(10, 5),
            font=("DejaVu Sans", 9, "bold"),
        )
    for style_name, background_role, foreground_role in (
        ("TestNotRun.TLabel", "test_not_run", "test_not_run_text"),
        ("TestRunning.TLabel", "test_running", "test_running_text"),
        ("TestPass.TLabel", "test_pass", "test_pass_text"),
        ("TestFail.TLabel", "test_fail", "test_fail_text"),
    ):
        style.configure(
            style_name,
            background=color(background_role),
            foreground=color(foreground_role),
            bordercolor=color("border"),
            borderwidth=1,
            relief="solid",
            padding=(2, 4),
        )

    style.configure(
        "TButton",
        background=color("surface"),
        foreground=color("ink"),
        bordercolor=color("border"),
        borderwidth=1,
        relief="solid",
        padding=(12, 7),
    )
    style.map(
        "TButton",
        background=[
            ("active", color("button_active")),
            ("disabled", color("disabled")),
        ],
        foreground=[
            ("active", color("button_active_text")),
            ("disabled", color("disabled_text")),
        ],
    )
    style.configure(
        "Primary.TButton",
        background=color("primary_action"),
        foreground=color("primary_action_text"),
        bordercolor=color("primary_action"),
    )
    style.map(
        "Primary.TButton",
        background=[
            ("active", color("primary_action_active")),
            ("disabled", color("disabled")),
        ],
        foreground=[
            ("active", color("active_accent_text")),
            ("disabled", color("disabled_text")),
        ],
    )
    style.configure(
        "Danger.TButton",
        background=color("surface"),
        foreground=color("danger"),
        bordercolor=color("danger"),
    )
    style.map(
        "Danger.TButton",
        background=[
            ("active", color("danger_active")),
            ("disabled", color("disabled")),
        ],
        foreground=[
            ("active", color("danger_active_text")),
            ("disabled", color("disabled_text")),
        ],
        bordercolor=[("disabled", color("border"))],
    )

    style.configure(
        "TEntry",
        fieldbackground=color("surface"),
        foreground=color("ink"),
        bordercolor=color("border"),
        lightcolor=color("border"),
        darkcolor=color("border"),
        borderwidth=1,
        padding=7,
    )
    style.configure(
        "TCombobox",
        fieldbackground=color("surface"),
        foreground=color("ink"),
        bordercolor=color("border"),
        padding=6,
    )
    style.configure(
        "Treeview",
        background=color("surface"),
        fieldbackground=color("surface"),
        foreground=color("ink"),
        bordercolor=color("border"),
        borderwidth=1,
        relief="solid",
        rowheight=30,
    )
    style.configure(
        "Treeview.Heading",
        background=color("header"),
        foreground=color("header_text"),
        bordercolor=color("border"),
        relief="solid",
        font=("DejaVu Sans", 9, "bold"),
        padding=(8, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", color("selection"))],
        foreground=[("selected", color("selection_text"))],
    )

    style.configure("TNotebook", background=color("canvas"), borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=color("header"),
        foreground=color("header_text"),
        bordercolor=color("border"),
        borderwidth=1,
        padding=(18, 9),
    )
    style.map(
        "TNotebook.Tab",
        background=[
            ("selected", color("tab_selected")),
            ("active", color("tab_active")),
        ],
        foreground=[
            ("selected", color("tab_selected_text")),
            ("active", color("tab_active_text")),
        ],
    )
    style.configure(
        "Transfer.Horizontal.TProgressbar",
        background=color("progress"),
        troughcolor=color("surface"),
        bordercolor=color("border"),
        lightcolor=color("progress"),
        darkcolor=color("progress"),
        thickness=14,
    )


def _configure_fonts(root: tk.Tk) -> None:
    """Use one readable Ubuntu-available family for all named Tk fonts."""

    for font_name in (
        "TkDefaultFont",
        "TkTextFont",
        "TkMenuFont",
        "TkHeadingFont",
        "TkCaptionFont",
        "TkSmallCaptionFont",
        "TkIconFont",
        "TkTooltipFont",
    ):
        try:
            named_font = font.nametofont(font_name, root=root)
        except tk.TclError:
            continue
        named_font.configure(family="DejaVu Sans", size=10)
