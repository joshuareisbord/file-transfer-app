"""Executable entry point for Work Transfer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from work_transfer_app import __version__


def _run_self_check() -> int:
    """Validate packaged transport, localization, and application resources."""

    try:
        import asyncssh
        import resvg_py
        from PIL import Image

        from work_transfer_app.config import load_mock_tests, load_update_destinations
        from work_transfer_app.localization import Translator

        _ = asyncssh.scp
        _ = Image.open
        _ = resvg_py.__version__
        _ = Translator("en").t("app.title")
        _ = load_update_destinations()
        _ = load_mock_tests()
    except (ImportError, OSError, TypeError, ValueError) as error:
        print(f"work-transfer: self-check failed: {error}", file=sys.stderr)
        return 1
    print(
        "work-transfer: ready (SCP transport, language, branding, and application "
        "config resources loaded)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Start the GUI or run the packaged-executable self-check."""

    parser = argparse.ArgumentParser(prog="work-transfer")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--logo", type=Path, metavar="FILE")
    parser.add_argument("--version", action="version", version=__version__)
    arguments = parser.parse_args(argv)

    if arguments.self_check:
        return _run_self_check()

    from work_transfer_app.ui import create_window
    from work_transfer_app.ui.logo import LogoLoadError

    try:
        window = create_window(logo_path=arguments.logo)
    except LogoLoadError as error:
        parser.error(str(error))
    window.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
