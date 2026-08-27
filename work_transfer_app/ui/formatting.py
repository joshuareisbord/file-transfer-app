"""Localized formatting helpers for transfer measurements."""

from __future__ import annotations

import math

from work_transfer_app.ui.contracts import TextTranslatorLike

_KIBIBYTE = 1024
_MEBIBYTE = _KIBIBYTE**2
_GIBIBYTE = _KIBIBYTE**3


def format_byte_count(value: int, translator: TextTranslatorLike) -> str:
    """Format a non-negative byte count with a localized binary unit."""

    safe_value = max(0, value)
    if safe_value < _KIBIBYTE:
        return translator.t("units.bytes", value=safe_value)
    if safe_value < _MEBIBYTE:
        return translator.t("units.kibibytes", value=f"{safe_value / _KIBIBYTE:.1f}")
    if safe_value < _GIBIBYTE:
        return translator.t("units.mebibytes", value=f"{safe_value / _MEBIBYTE:.1f}")
    return translator.t("units.gibibytes", value=f"{safe_value / _GIBIBYTE:.1f}")


def format_transfer_rate(value: float, translator: TextTranslatorLike) -> str:
    """Format a byte-per-second measurement with localized units."""

    byte_count = format_byte_count(max(0, math.floor(value)), translator)
    return translator.t("units.per_second", value=byte_count)


def format_eta(
    seconds: float | None,
    translator: TextTranslatorLike,
    *,
    is_stalled: bool = False,
) -> str:
    """Format an ETA or one of its non-numeric progress states."""

    if is_stalled:
        return translator.t("status.eta_stalled")
    if seconds is None or not math.isfinite(seconds):
        return translator.t("status.eta_calculating")

    rounded_seconds = max(0, math.ceil(seconds))
    if rounded_seconds < 60:
        return translator.t("units.duration_seconds", value=rounded_seconds)
    if rounded_seconds < 3600:
        minutes, remaining_seconds = divmod(rounded_seconds, 60)
        return translator.t(
            "units.duration_minutes",
            minutes=minutes,
            seconds=remaining_seconds,
        )
    hours, remaining = divmod(rounded_seconds, 3600)
    minutes = remaining // 60
    return translator.t("units.duration_hours", hours=hours, minutes=minutes)
