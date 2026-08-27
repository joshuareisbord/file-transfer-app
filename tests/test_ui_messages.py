from typing import Literal

import pytest

from work_transfer_app.transfer import TransferErrorKind
from work_transfer_app.ui.messages import localized_backend_message


class RecordingTranslator:
    """Record the catalog lookup selected for a backend diagnostic."""

    def __init__(self) -> None:
        """Start without recorded localization calls."""

        self.calls: list[tuple[str, dict[str, object]]] = []

    def t(self, key: str, **values: object) -> str:
        """Return the selected catalog key for deterministic assertions."""

        self.calls.append((key, values))
        return key


@pytest.mark.parametrize(
    ("token", "translation_key"),
    [
        ("source_file_missing", "errors.source_file_missing"),
        ("destination_file_exists", "errors.destination_file_exists"),
        ("identity_file_missing", "errors.identity_file_missing"),
        ("known_hosts_missing", "errors.known_hosts_missing"),
    ],
)
def test_stable_backend_tokens_are_translated_without_raw_detail(
    token: str,
    translation_key: str,
) -> None:
    """Keep implementation tokens out of all user-facing failure text."""

    translator = RecordingTranslator()

    localized_backend_message(
        translator,
        token,
        TransferErrorKind.FILE,
        context="transfer",
    )

    assert translator.calls == [(translation_key, {})]


@pytest.mark.parametrize(
    ("kind", "context", "message", "expected"),
    [
        (
            TransferErrorKind.AUTHENTICATION,
            "connection",
            "Permission denied",
            ("errors.authentication", {}),
        ),
        (
            TransferErrorKind.HOST_KEY,
            "connection",
            "Host key rejected",
            ("errors.host_key", {}),
        ),
        (
            TransferErrorKind.CONNECTION,
            "connection",
            "Connection reset by peer",
            ("errors.connection_failed", {"detail": "Connection reset by peer"}),
        ),
        (
            TransferErrorKind.FILE,
            "transfer",
            "Remote write failed",
            ("errors.transfer", {"message": "Remote write failed"}),
        ),
    ],
)
def test_failure_categories_choose_a_localized_surface(
    kind: TransferErrorKind,
    context: Literal["connection", "queue", "transfer"],
    message: str,
    expected: tuple[str, dict[str, object]],
) -> None:
    """Wrap diagnostics with the correct localized context or safe category."""

    translator = RecordingTranslator()

    localized_backend_message(translator, message, kind, context=context)

    assert translator.calls == [expected]


def test_unknown_stable_token_uses_generic_text_without_echoing_the_token() -> None:
    """Hide future internal tokens until a deliberate translation is added."""

    translator = RecordingTranslator()

    localized_backend_message(
        translator,
        "future_backend_token",
        TransferErrorKind.UNKNOWN,
        context="transfer",
    )

    assert translator.calls == [("errors.unexpected", {})]
