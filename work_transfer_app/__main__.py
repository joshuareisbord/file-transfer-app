"""Executable entry point for Work Transfer."""

from __future__ import annotations

import argparse
import sys

from work_transfer_app import __version__


def _run_self_check() -> int:
    """Validate the packaged transport and localization resources."""

    try:
        import asyncssh

        from work_transfer_app.localization import Translator

        _ = asyncssh.scp
        _ = Translator("en").t("app.title")
    except (ImportError, OSError, TypeError, ValueError) as error:
        print(f"work-transfer: self-check failed: {error}", file=sys.stderr)
        return 1
    print("work-transfer: ready (SCP transport and language resources loaded)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Start the GUI or run the packaged-executable self-check."""

    parser = argparse.ArgumentParser(prog="work-transfer")
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    arguments = parser.parse_args(argv)

    if arguments.self_check:
        return _run_self_check()

    from work_transfer_app.ui import create_window

    create_window().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
