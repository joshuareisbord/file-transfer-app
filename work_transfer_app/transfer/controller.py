"""Thread-safe single-transfer controller backed by one asyncio event loop."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from pathlib import Path
from queue import Queue

from work_transfer_app.transfer.backend import ScpTransferBackend, TransferBackend
from work_transfer_app.transfer.models import (
    ConnectionConfig,
    ConnectionDegradedEvent,
    ConnectionTestedEvent,
    ConnectionTestResult,
    TransferErrorKind,
    TransferEvent,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferProgressEvent,
    TransferResult,
    TransferState,
    TransferStateEvent,
)

_CONTROL_TIMEOUT_SECONDS = 2.0


class TransferController:
    """Coordinate connection tests and one active transfer off the UI thread."""

    def __init__(self, backend: TransferBackend | None = None) -> None:
        """Start the controller's dedicated background asyncio loop."""

        self.events: Queue[TransferEvent] = Queue()
        self._backend = backend or ScpTransferBackend()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._state_lock = threading.Lock()
        self._tested_connection: ConnectionConfig | None = None
        self._connection_test_config: ConnectionConfig | None = None
        self._connection_test_generation = 0
        self._active_job_id: str | None = None
        self._closed = False

        self._current_transfer_task: asyncio.Task[None] | None = None
        self._shutdown_future: Future[None] | None = None
        self._shutting_down = False

        self._thread = threading.Thread(
            target=self._run_loop,
            name="work-transfer-asyncio",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait()

    @property
    def tested_connection(self) -> ConnectionConfig | None:
        """Return the most recently successful connection snapshot."""

        with self._state_lock:
            return self._tested_connection

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Test a connection asynchronously and return a thread-safe future."""

        with self._state_lock:
            if self._closed:
                raise RuntimeError("controller_closed")
            self._connection_test_generation += 1
            generation = self._connection_test_generation
            self._tested_connection = None
            self._connection_test_config = config
            return asyncio.run_coroutine_threadsafe(
                self._test_connection(config, generation), self._loop
            )

    def invalidate_connection(self) -> None:
        """Prevent new transfers from using connection fields which were edited."""

        with self._state_lock:
            self._connection_test_generation += 1
            self._tested_connection = None
            if self._connection_test_config is not None:
                self.events.put(
                    ConnectionTestedEvent(
                        ConnectionTestResult(
                            self._connection_test_config,
                            False,
                            "connection_invalidated",
                        )
                    )
                )

    def start(self, source: Path, remote_directory: str) -> TransferJob:
        """Start a file transfer using the last successfully tested connection."""

        normalized_source = source.expanduser().absolute()

        with self._state_lock:
            if self._closed:
                raise RuntimeError("controller_closed")
            if self._active_job_id is not None:
                raise RuntimeError("transfer_active")
            connection = self._tested_connection
            if connection is None:
                raise RuntimeError("connection_not_tested")

            job = TransferJob.create(normalized_source, remote_directory, connection)
            self._active_job_id = job.id
            try:
                self._loop.call_soon_threadsafe(self._start_on_loop, job)
            except RuntimeError:
                self._active_job_id = None
                job.close_source()
                raise
            return job

    def abort(self) -> bool:
        """Request cancellation of the active transfer."""

        with self._state_lock:
            if self._closed:
                raise RuntimeError("controller_closed")
            future = asyncio.run_coroutine_threadsafe(self._abort_on_loop(), self._loop)
        return future.result(timeout=_CONTROL_TIMEOUT_SECONDS)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel active work without abandoning remote cleanup on timeout."""

        with self._state_lock:
            future = self._shutdown_future
            if future is None:
                self._closed = True
                future = asyncio.run_coroutine_threadsafe(
                    self._shutdown_on_loop(),
                    self._loop,
                )
                self._shutdown_future = future
                future.add_done_callback(self._stop_loop_after_shutdown)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError as error:
            raise TimeoutError("shutdown_cleanup_timeout") from error
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError("shutdown_cleanup_timeout")

    def _stop_loop_after_shutdown(self, _future: Future[None]) -> None:
        """Stop the worker loop only after transfer cleanup has completed."""

        self._loop.call_soon_threadsafe(self._loop.stop)

    async def _test_connection(
        self, config: ConnectionConfig, generation: int
    ) -> ConnectionTestResult:
        """Run a backend connection test and publish its current result."""

        try:
            result = await self._backend.test_connection(config)
        except Exception as error:  # noqa: BLE001 - normalize backend failures
            result = ConnectionTestResult(
                config,
                False,
                str(error).strip() or type(error).__name__,
                TransferErrorKind.UNKNOWN,
            )

        with self._state_lock:
            if generation != self._connection_test_generation:
                return replace(
                    result,
                    is_success=False,
                    message="connection_test_stale",
                    error_kind=TransferErrorKind.NONE,
                    is_stale=True,
                )
            if result.is_success:
                self._tested_connection = config
            self.events.put(ConnectionTestedEvent(result))
        return result

    def _start_on_loop(self, job: TransferJob) -> None:
        """Start one backend transfer on its owning event-loop thread."""

        if self._shutting_down:
            self._clear_active_job(job.id)
            job.close_source()
            return
        self.events.put(TransferStateEvent(job.id, TransferState.CONNECTING))
        self.events.put(TransferStateEvent(job.id, TransferState.TRANSFERRING))
        self._current_transfer_task = asyncio.create_task(self._run_transfer(job))

    async def _run_transfer(self, job: TransferJob) -> None:
        """Execute one backend transfer and publish its terminal outcome."""

        try:
            try:
                result = await self._backend.transfer(job, self._publish_progress)
            except asyncio.CancelledError:
                result = TransferResult(job.id, TransferState.ABORTED)
            except Exception as error:  # noqa: BLE001 - isolate backend failures
                result = TransferResult(
                    job.id,
                    TransferState.FAILED,
                    str(error).strip() or type(error).__name__,
                    TransferErrorKind.UNKNOWN,
                )
        finally:
            job.close_source()

        should_degrade = False
        if result.error_kind.degrades_connection and not self._shutting_down:
            with self._state_lock:
                if self._tested_connection == job.connection:
                    self._connection_test_generation += 1
                    self._tested_connection = None
                    should_degrade = True
        self._clear_active_job(job.id)
        self._current_transfer_task = None
        self.events.put(TransferFinishedEvent(result))
        if should_degrade:
            self.events.put(ConnectionDegradedEvent(result.message, result.error_kind))

    async def _abort_on_loop(self) -> bool:
        """Cancel the active backend task on its owning event loop."""

        task = self._current_transfer_task
        if task is None or task.done():
            return False
        with self._state_lock:
            job_id = self._active_job_id
        if job_id is None:
            return False
        self.events.put(TransferStateEvent(job_id, TransferState.CANCELLING))
        task.cancel()
        return True

    async def _shutdown_on_loop(self) -> None:
        """Cancel active work while allowing backend cleanup to run."""

        self._shutting_down = True
        task = self._current_transfer_task
        if task is not None and not task.done():
            task.cancel()
            await task
        with self._state_lock:
            self._active_job_id = None

    def _publish_progress(self, progress: TransferProgress) -> None:
        """Publish immutable progress from the controller's event-loop thread."""

        self.events.put(TransferProgressEvent(progress))

    def _clear_active_job(self, job_id: str) -> None:
        """Release the active slot only when it still belongs to the given job."""

        with self._state_lock:
            if self._active_job_id == job_id:
                self._active_job_id = None

    def _run_loop(self) -> None:
        """Own and cleanly close the background asyncio event loop."""

        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        self._loop.close()
