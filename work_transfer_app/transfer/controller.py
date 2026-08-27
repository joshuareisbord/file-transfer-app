"""Thread-safe sequential transfer queue backed by one asyncio event loop."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from pathlib import Path
from queue import Queue

from work_transfer_app.transfer.backend import (
    ScpTransferBackend,
    TransferBackend,
)
from work_transfer_app.transfer.models import (
    ConnectionConfig,
    ConnectionTestedEvent,
    ConnectionTestResult,
    JobQueuedEvent,
    JobRemovedEvent,
    QueuePausedEvent,
    QueueResumedEvent,
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


class TransferQueueController:
    """Coordinate connection tests and sequential transfers off the UI thread."""

    def __init__(self, backend: TransferBackend | None = None) -> None:
        """Start the controller's dedicated background asyncio loop."""

        self.events: Queue[TransferEvent] = Queue()
        self._backend = backend or ScpTransferBackend()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._state_lock = threading.Lock()
        self._tested_connection: ConnectionConfig | None = None
        self._connection_test_generation = 0
        self._work_count = 0
        self._paused_snapshot = False
        self._closed = False

        self._jobs: deque[TransferJob] = deque()
        self._processor_task: asyncio.Task[None] | None = None
        self._current_transfer_task: asyncio.Task[TransferResult] | None = None
        self._current_job: TransferJob | None = None
        self._paused = False
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

    @property
    def has_work(self) -> bool:
        """Return whether active or queued work remains."""

        with self._state_lock:
            return self._work_count > 0

    @property
    def work_count(self) -> int:
        """Return the combined active and queued job count."""

        with self._state_lock:
            return self._work_count

    @property
    def is_paused(self) -> bool:
        """Return whether a connection failure paused the queue."""

        with self._state_lock:
            return self._paused_snapshot

    def test_connection(self, config: ConnectionConfig) -> Future[ConnectionTestResult]:
        """Test a connection asynchronously and return a thread-safe future."""

        self._ensure_open()
        with self._state_lock:
            self._connection_test_generation += 1
            generation = self._connection_test_generation
            self._tested_connection = None
        return asyncio.run_coroutine_threadsafe(
            self._test_connection(config, generation), self._loop
        )

    def invalidate_connection(self) -> None:
        """Prevent new jobs from using connection fields which were edited."""

        with self._state_lock:
            self._connection_test_generation += 1
            self._tested_connection = None

    def enqueue(self, source: Path, remote_directory: str) -> TransferJob:
        """Queue a file using the last successfully tested config snapshot."""

        self._ensure_open()
        normalized_source = source.expanduser().resolve()
        if not normalized_source.is_file():
            raise ValueError("source_file_missing")
        with self._state_lock:
            connection = self._tested_connection
            if connection is None:
                raise RuntimeError("connection_not_tested")
        job = TransferJob.create(normalized_source, remote_directory, connection)
        with self._state_lock:
            self._work_count += 1
        self._loop.call_soon_threadsafe(self._enqueue_on_loop, job)
        return job

    def remove(self, job_id: str) -> bool:
        """Remove a waiting job without affecting an active transfer."""

        self._ensure_open()
        future = asyncio.run_coroutine_threadsafe(
            self._remove_on_loop(job_id), self._loop
        )
        return future.result(timeout=_CONTROL_TIMEOUT_SECONDS)

    def abort(self) -> bool:
        """Request cancellation of the active job and keep later jobs queued."""

        self._ensure_open()
        future = asyncio.run_coroutine_threadsafe(self._abort_on_loop(), self._loop)
        return future.result(timeout=_CONTROL_TIMEOUT_SECONDS)

    def resume(self) -> bool:
        """Resume a queue explicitly after a connection-class failure."""

        self._ensure_open()
        future = asyncio.run_coroutine_threadsafe(self._resume_on_loop(), self._loop)
        return future.result(timeout=_CONTROL_TIMEOUT_SECONDS)

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel active work, clear waiting jobs, and stop the loop."""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        future = asyncio.run_coroutine_threadsafe(self._shutdown_on_loop(), self._loop)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=timeout)

    async def _test_connection(
        self, config: ConnectionConfig, generation: int
    ) -> ConnectionTestResult:
        """Run a backend connection test and publish its result."""

        try:
            result = await self._backend.test_connection(config)
        except Exception as error:  # noqa: BLE001 - normalize backend failures
            result = ConnectionTestResult(
                config,
                False,
                str(error).strip() or type(error).__name__,
                TransferErrorKind.UNKNOWN,
            )
        can_resume_queue = not self._paused or all(
            job.connection == config for job in self._jobs
        )
        result = replace(result, can_resume_queue=can_resume_queue)
        with self._state_lock:
            if generation != self._connection_test_generation:
                return replace(
                    result,
                    is_success=False,
                    message="connection_test_stale",
                    error_kind=TransferErrorKind.NONE,
                    is_stale=True,
                    can_resume_queue=False,
                )
            if result.is_success:
                self._tested_connection = config
            self.events.put(ConnectionTestedEvent(result))
        return result

    def _enqueue_on_loop(self, job: TransferJob) -> None:
        """Add a job on the owning event-loop thread and start processing."""

        if self._shutting_down:
            self._decrement_work_count()
            return
        self._jobs.append(job)
        self.events.put(JobQueuedEvent(job))
        self._ensure_processor()

    async def _remove_on_loop(self, job_id: str) -> bool:
        """Remove a matching waiting job on the event-loop thread."""

        for index, job in enumerate(self._jobs):
            if job.id != job_id:
                continue
            del self._jobs[index]
            self._decrement_work_count()
            self.events.put(JobRemovedEvent(job_id))
            return True
        return False

    async def _abort_on_loop(self) -> bool:
        """Cancel the active backend task on its owning event loop."""

        task = self._current_transfer_task
        job = self._current_job
        if task is None or task.done() or job is None:
            return False
        self.events.put(TransferStateEvent(job.id, TransferState.CANCELLING))
        task.cancel()
        return True

    async def _resume_on_loop(self) -> bool:
        """Clear a paused state and restart pending sequential processing."""

        if not self._paused:
            return False
        with self._state_lock:
            tested_connection = self._tested_connection
        if tested_connection is None or any(
            job.connection != tested_connection for job in self._jobs
        ):
            return False
        self._paused = False
        with self._state_lock:
            self._paused_snapshot = False
        self.events.put(QueueResumedEvent())
        self._ensure_processor()
        return True

    async def _shutdown_on_loop(self) -> None:
        """Drain controller tasks while allowing backend cleanup to run."""

        self._shutting_down = True
        waiting_count = len(self._jobs)
        self._jobs.clear()
        if waiting_count:
            with self._state_lock:
                self._work_count = max(self._work_count - waiting_count, 0)
        if self._current_transfer_task is not None:
            self._current_transfer_task.cancel()
        if self._processor_task is not None:
            await self._processor_task

    def _ensure_processor(self) -> None:
        """Start one queue processor when runnable work is waiting."""

        if self._shutting_down or self._paused or not self._jobs:
            return
        if self._processor_task is not None and not self._processor_task.done():
            return
        self._processor_task = asyncio.create_task(self._process_queue())

    async def _process_queue(self) -> None:
        """Run waiting jobs serially until empty, paused, or shutting down."""

        while self._jobs and not self._paused and not self._shutting_down:
            job = self._jobs.popleft()
            self._current_job = job
            self.events.put(TransferStateEvent(job.id, TransferState.CONNECTING))
            self.events.put(TransferStateEvent(job.id, TransferState.TRANSFERRING))
            self._current_transfer_task = asyncio.create_task(
                self._backend.transfer(job, self._publish_progress)
            )
            try:
                result = await self._current_transfer_task
            except asyncio.CancelledError:
                result = TransferResult(job.id, TransferState.ABORTED)
            except Exception as error:  # noqa: BLE001 - isolate backend failures
                result = TransferResult(
                    job.id,
                    TransferState.FAILED,
                    str(error).strip() or type(error).__name__,
                    TransferErrorKind.UNKNOWN,
                )
            self.events.put(TransferFinishedEvent(result))
            self._decrement_work_count()
            self._current_transfer_task = None
            self._current_job = None

            if result.error_kind.pauses_queue and not self._shutting_down:
                self._paused = True
                with self._state_lock:
                    self._paused_snapshot = True
                    self._tested_connection = None
                self.events.put(QueuePausedEvent(result.message, result.error_kind))
                return

    def _publish_progress(self, progress: TransferProgress) -> None:
        """Publish immutable progress from the controller's event-loop thread."""

        self.events.put(TransferProgressEvent(progress))

    def _decrement_work_count(self) -> None:
        """Decrease the externally visible active-plus-waiting count safely."""

        with self._state_lock:
            self._work_count = max(self._work_count - 1, 0)

    def _ensure_open(self) -> None:
        """Reject new work after shutdown begins."""

        with self._state_lock:
            if self._closed:
                raise RuntimeError("controller_closed")

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
