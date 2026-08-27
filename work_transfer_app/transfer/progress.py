"""Rolling throughput, ETA, throttling, and stall calculation."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from work_transfer_app.transfer.models import TransferProgress

_MIN_EMIT_INTERVAL_SECONDS = 0.25
_RATE_WINDOW_SECONDS = 5.0
_ETA_MINIMUM_SECONDS = 1.0
_ETA_MINIMUM_BYTES = 256 * 1024
_STALL_SECONDS = 5.0


class ProgressEstimator:
    """Calculate throttled progress from exact cumulative byte counts."""

    def __init__(
        self,
        job_id: str,
        total_bytes: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Start an estimator for one immutable job and total byte count."""

        self._job_id = job_id
        self._total_bytes = max(total_bytes, 0)
        self._clock = clock
        self._started_at = clock()
        self._last_advanced_at = self._started_at
        self._last_emitted_at: float | None = None
        self._transferred_bytes = 0
        self._samples: deque[tuple[float, int]] = deque([(self._started_at, 0)])

    def record(
        self,
        transferred_bytes: int,
        total_bytes: int | None = None,
        *,
        force: bool = False,
    ) -> TransferProgress | None:
        """Record cumulative bytes and return a progress item when due."""

        now = self._clock()
        transferred = max(transferred_bytes, 0)
        if total_bytes is not None:
            self._total_bytes = max(total_bytes, transferred, 0)
        else:
            self._total_bytes = max(self._total_bytes, transferred)
        if transferred > self._transferred_bytes:
            self._last_advanced_at = now
        self._transferred_bytes = max(self._transferred_bytes, transferred)
        self._samples.append((now, self._transferred_bytes))
        self._trim_samples(now)
        if not force and not self._can_emit(now):
            return None
        self._last_emitted_at = now
        return self._snapshot(
            now, is_stalled=now - self._last_advanced_at >= _STALL_SECONDS
        )

    def complete(self) -> TransferProgress:
        """Return a forced final snapshot without reading the source again."""

        progress = self.record(self._total_bytes, force=True)
        assert progress is not None
        return progress

    def stalled(self) -> TransferProgress | None:
        """Return a stalled snapshot after five seconds without new bytes."""

        now = self._clock()
        if now - self._last_advanced_at < _STALL_SECONDS:
            return None
        if not self._can_emit(now):
            return None
        self._trim_samples(now)
        self._last_emitted_at = now
        return self._snapshot(now, is_stalled=True)

    def _can_emit(self, now: float) -> bool:
        """Limit ordinary UI progress messages to four per second."""

        return (
            self._last_emitted_at is None
            or now - self._last_emitted_at >= _MIN_EMIT_INTERVAL_SECONDS
        )

    def _trim_samples(self, now: float) -> None:
        """Keep the smallest sample set covering the five-second window."""

        cutoff = now - _RATE_WINDOW_SECONDS
        while len(self._samples) > 1 and self._samples[1][0] <= cutoff:
            self._samples.popleft()

    def _snapshot(self, now: float, *, is_stalled: bool) -> TransferProgress:
        """Build an immutable progress view from current samples."""

        oldest_time, oldest_bytes = self._samples[0]
        newest_time, newest_bytes = self._samples[-1]
        duration = newest_time - oldest_time
        rate = (
            (newest_bytes - oldest_bytes) / duration
            if duration > 0 and newest_bytes > oldest_bytes
            else None
        )
        remaining_bytes = max(self._total_bytes - self._transferred_bytes, 0)
        eta = None
        if (
            not is_stalled
            and rate is not None
            and now - self._started_at >= _ETA_MINIMUM_SECONDS
            and self._transferred_bytes >= _ETA_MINIMUM_BYTES
        ):
            eta = remaining_bytes / rate
        percent = (
            100.0
            if self._total_bytes == 0
            else (self._transferred_bytes / self._total_bytes) * 100.0
        )
        return TransferProgress(
            job_id=self._job_id,
            transferred_bytes=self._transferred_bytes,
            total_bytes=self._total_bytes,
            percent=percent,
            bytes_per_second=rate,
            eta_seconds=eta,
            is_stalled=is_stalled,
        )
