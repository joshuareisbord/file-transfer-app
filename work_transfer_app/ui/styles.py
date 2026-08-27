"""Light-only industrial visual system for the Tk interface."""

from __future__ import annotations

import tkinter as tk
from tkinter import font, ttk

_CANVAS = "#EEF1F2"
_SURFACE = "#FFFFFF"
_HEADER = "#DDE3E5"
_BORDER = "#AEB8BC"
_INK = "#17252C"
_MUTED = "#526168"
_TEAL = "#006E69"
_TEAL_DARK = "#005954"
_ERROR = "#9C2F2A"
_NOTICE = "#765B00"
_DISABLED = "#7D898E"


def configure_styles(root: tk.Tk) -> None:
    """Configure a square, high-contrast visual system for the application."""

    root.configure(background=_CANVAS)
    _configure_fonts(root)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("TFrame", background=_CANVAS)
    style.configure("Body.TFrame", background=_CANVAS)
    style.configure(
        "Panel.TFrame",
        background=_SURFACE,
        bordercolor=_BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.configure("PanelContent.TFrame", background=_SURFACE, borderwidth=0)
    style.configure(
        "Header.TFrame",
        background=_HEADER,
        bordercolor=_BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.configure(
        "StatusTray.TFrame",
        background=_HEADER,
        bordercolor=_BORDER,
        borderwidth=1,
        relief="solid",
    )
    style.configure("StatusContent.TFrame", background=_HEADER, borderwidth=0)

    style.configure("TLabel", background=_SURFACE, foreground=_INK)
    style.configure(
        "AppTitle.TLabel",
        background=_HEADER,
        foreground=_INK,
        font=("DejaVu Sans", 16, "bold"),
    )
    style.configure("AppSubtitle.TLabel", background=_HEADER, foreground=_MUTED)
    style.configure(
        "SectionTitle.TLabel",
        background=_CANVAS,
        foreground=_INK,
        font=("DejaVu Sans", 15, "bold"),
    )
    style.configure("Muted.TLabel", background=_CANVAS, foreground=_MUTED)
    style.configure(
        "PanelHeading.TLabel",
        background=_SURFACE,
        foreground=_INK,
        font=("DejaVu Sans", 11, "bold"),
    )
    style.configure("MutedPanel.TLabel", background=_SURFACE, foreground=_MUTED)
    style.configure("Error.TLabel", background=_SURFACE, foreground=_ERROR)
    style.configure("Notice.TLabel", background=_SURFACE, foreground=_NOTICE)
    style.configure("Data.TLabel", background=_SURFACE, foreground=_INK)
    style.configure("InlineStatus.TLabel", background=_SURFACE, foreground=_MUTED)
    style.configure(
        "StatusFile.TLabel",
        background=_HEADER,
        foreground=_INK,
        font=("DejaVu Sans", 10, "bold"),
    )
    style.configure("StatusState.TLabel", background=_HEADER, foreground=_TEAL_DARK)
    style.configure("StatusMeta.TLabel", background=_HEADER, foreground=_MUTED)

    style.configure(
        "TButton",
        background=_SURFACE,
        foreground=_INK,
        bordercolor=_BORDER,
        borderwidth=1,
        relief="solid",
        padding=(12, 7),
    )
    style.map(
        "TButton",
        background=[("active", _HEADER), ("disabled", _CANVAS)],
        foreground=[("disabled", _DISABLED)],
    )
    style.configure(
        "Primary.TButton",
        background=_TEAL,
        foreground=_SURFACE,
        bordercolor=_TEAL_DARK,
    )
    style.map(
        "Primary.TButton",
        background=[("active", _TEAL_DARK), ("disabled", _DISABLED)],
        foreground=[("disabled", _SURFACE)],
    )
    style.configure(
        "Danger.TButton",
        background=_SURFACE,
        foreground=_ERROR,
        bordercolor=_ERROR,
    )
    style.map("Danger.TButton", background=[("active", "#F8E8E7")])

    style.configure(
        "TEntry",
        fieldbackground=_SURFACE,
        foreground=_INK,
        bordercolor=_BORDER,
        lightcolor=_BORDER,
        darkcolor=_BORDER,
        borderwidth=1,
        padding=7,
    )
    style.configure(
        "TCombobox",
        fieldbackground=_SURFACE,
        foreground=_INK,
        bordercolor=_BORDER,
        padding=6,
    )
    style.configure(
        "Treeview",
        background=_SURFACE,
        fieldbackground=_SURFACE,
        foreground=_INK,
        bordercolor=_BORDER,
        borderwidth=1,
        relief="solid",
        rowheight=30,
    )
    style.configure(
        "Treeview.Heading",
        background=_HEADER,
        foreground=_INK,
        bordercolor=_BORDER,
        relief="solid",
        font=("DejaVu Sans", 9, "bold"),
        padding=(8, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", _TEAL)],
        foreground=[("selected", _SURFACE)],
    )

    style.configure("TNotebook", background=_CANVAS, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=_HEADER,
        foreground=_INK,
        bordercolor=_BORDER,
        borderwidth=1,
        padding=(18, 9),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", _SURFACE), ("active", "#E8ECEE")],
        foreground=[("selected", _TEAL_DARK)],
        expand=[("selected", (0, 0, 0, 1))],
    )
    style.configure(
        "Transfer.Horizontal.TProgressbar",
        background=_TEAL,
        troughcolor=_SURFACE,
        bordercolor=_BORDER,
        lightcolor=_TEAL,
        darkcolor=_TEAL,
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
