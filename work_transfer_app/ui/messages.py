"""Translate backend diagnostics before they enter user-facing widgets."""

from __future__ import annotations

import re
from typing import Literal

from work_transfer_app.transfer import TransferErrorKind
from work_transfer_app.ui.contracts import TextTranslatorLike

MessageContext = Literal["connection", "transfer"]

_STABLE_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_TOKEN_TRANSLATIONS = {
    "source_file_missing": "errors.source_file_missing",
    "destination_file_exists": "errors.remote_file_exists",
    "identity_file_missing": "errors.identity_file_missing",
    "known_hosts_missing": "errors.known_hosts_missing",
    "connection_not_tested": "connection.test_required",
    "transfer_active": "errors.transfer_active",
    "invalid_remote_directory": "errors.remote_directory_invalid",
    "invalid_host": "validation.host_required",
    "invalid_username": "validation.username_required",
    "invalid_port": "validation.port_range",
}


def localized_backend_message(
    translator: TextTranslatorLike,
    message: str,
    error_kind: TransferErrorKind,
    *,
    context: MessageContext,
) -> str:
    """Map stable tokens and diagnostic failures to localized UI text."""

    normalized_message = message.strip()
    translation_key = _TOKEN_TRANSLATIONS.get(normalized_message)
    if translation_key is not None:
        return translator.t(translation_key)
    if error_kind is TransferErrorKind.AUTHENTICATION:
        return translator.t("errors.authentication")
    if error_kind is TransferErrorKind.HOST_KEY:
        return translator.t("errors.host_key")
    if _STABLE_TOKEN.fullmatch(normalized_message):
        return translator.t("errors.unexpected")

    detail = normalized_message or translator.t("common.unavailable")
    if context == "connection":
        return translator.t("errors.connection_failed", detail=detail)
    return translator.t("errors.transfer", message=detail)
