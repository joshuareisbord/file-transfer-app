"""Narrow dependency contracts used by the desktop interface."""

from __future__ import annotations

import queue
from collections.abc import Mapping
from concurrent.futures import Future
from pathlib import Path
from typing import Protocol

from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionTestResult,
    TransferEvent,
    TransferJob,
)


class LanguageOption(Protocol):
    """Describe one language shown in the settings selector."""

    @property
    def code(self) -> str:
        """Return the stable language code."""

        ...

    @property
    def name(self) -> str:
        """Return the localized language name."""

        ...


class LocalizationNotice(Protocol):
    """Describe one non-fatal localization warning."""

    @property
    def translation_key(self) -> str:
        """Return the catalog key for this warning."""

        ...

    @property
    def values(self) -> Mapping[str, object]:
        """Return safe values used to format the warning."""

        ...


class TextTranslatorLike(Protocol):
    """Provide localized text to display-only helpers."""

    def t(self, key: str, **values: object) -> str:
        """Translate one catalog key with validated substitutions."""

        ...


class TranslatorLike(TextTranslatorLike, Protocol):
    """Provide localized text and the installed language catalog."""

    @property
    def languages(self) -> tuple[LanguageOption, ...]:
        """Return languages available for the next application start."""

        ...

    @property
    def warnings(self) -> tuple[LocalizationNotice, ...]:
        """Return non-fatal catalog warnings."""

        ...


class SettingsLike(Protocol):
    """Persist the small set of user-facing UI preferences."""

    @property
    def warnings(self) -> tuple[LocalizationNotice, ...]:
        """Return localized warning references from settings loading."""

        ...

    def load_language(self) -> str:
        """Load the language selected for this application start."""

        ...

    def save_language(self, language_code: str) -> None:
        """Persist the selected language for the next application start."""

        ...


class TransferControllerLike(Protocol):
    """Expose transfer operations without coupling widgets to a backend."""

    @property
    def events(self) -> queue.Queue[TransferEvent]:
        """Return the event stream consumed on the Tk thread."""

        ...

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Start a non-blocking connection test."""

        ...

    def invalidate_connection(self) -> None:
        """Prevent new jobs from using connection fields which were edited."""

        ...

    def enqueue(self, source: Path, remote_directory: str) -> TransferJob:
        """Add one file to the sequential transfer queue."""

        ...

    def remove(self, job_id: str) -> bool:
        """Remove a waiting transfer from the queue."""

        ...

    def abort(self) -> bool:
        """Request cancellation of the active transfer."""

        ...

    def resume(self) -> bool:
        """Resume a connection-paused queue after a successful retest."""

        ...

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel outstanding work and stop the transfer worker."""

        ...
