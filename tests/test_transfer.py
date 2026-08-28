from __future__ import annotations

import asyncio
import posixpath
import shlex
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Empty
from typing import Any, Self

import pytest

from work_transfer_app.transfer import (
    ConnectionConfig,
    ConnectionDegradedEvent,
    ConnectionTestedEvent,
    ConnectionTestResult,
    ScpTransferBackend,
    TransferController,
    TransferErrorKind,
    TransferFinishedEvent,
    TransferJob,
    TransferProgress,
    TransferResult,
    TransferState,
    TransferStateEvent,
)
from work_transfer_app.transfer.progress import ProgressEstimator


class _FakeSftpClient:
    """Model the remote operations used to commit an uploaded file."""

    def __init__(self, files: dict[str, bytes], home: str = "/home/transfer") -> None:
        self.files = files
        self.home = home
        self.operations: list[tuple[str, ...]] = []

    async def __aenter__(self) -> Self:
        """Open the fake SFTP session."""

        return self

    async def __aexit__(self, *_args: object) -> None:
        """Close the fake SFTP session."""

    async def stat(self, path: str) -> object:
        """Return an opaque stat result when a remote file exists."""

        self.operations.append(("stat", path))
        if path not in self.files:
            import asyncssh

            raise asyncssh.SFTPNoSuchFile("missing")
        return object()

    async def rename(self, source: str, destination: str) -> None:
        """Rename without overwriting an existing destination."""

        self.operations.append(("rename", source, destination))
        if destination in self.files:
            raise RuntimeError("destination exists")
        self.files[destination] = self.files.pop(source)

    async def remove(self, path: str) -> None:
        """Remove a remote file."""

        self.operations.append(("remove", path))
        self.files.pop(path, None)

    async def realpath(self, path: str) -> str:
        """Resolve a remote path against the fake account home directory."""

        self.operations.append(("realpath", path))
        if path == ".":
            return self.home
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(self.home, path))


class _FakeConnection:
    """Expose an SFTP session over an in-memory remote file system."""

    def __init__(self, files: dict[str, bytes], home: str = "/home/transfer") -> None:
        self.files = files
        self.sftp = _FakeSftpClient(files, home)

    async def __aenter__(self) -> Self:
        """Open the fake SSH connection."""

        return self

    async def __aexit__(self, *_args: object) -> None:
        """Close the fake SSH connection."""

    def start_sftp_client(self) -> _FakeSftpClient:
        """Create a fake SFTP client."""

        return self.sftp


class _FakeConnector:
    """Record SSH options and return a reusable fake connection."""

    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.kwargs: dict[str, object] = {}

    def __call__(self, host: str, port: int, **kwargs: object) -> _FakeConnection:
        """Return the configured connection and retain security options."""

        self.kwargs = {"host": host, "port": port, **kwargs}
        return self.connection


def _config(tmp_path: Path, host: str = "192.168.50.2") -> ConnectionConfig:
    """Create valid key and known-host files for a connection config."""

    identity = tmp_path / "id_ed25519"
    identity.write_text("private key")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("host key")
    return ConnectionConfig(
        host=host,
        username="transfer",
        identity_file=identity,
        known_hosts=known_hosts,
    )


def _raw_shell_path(shell_path: str) -> str:
    """Decode one POSIX-shell-quoted path without executing a shell."""

    tokens = shlex.split(shell_path, posix=True)
    assert len(tokens) == 1
    return tokens[0]


def _wait_for_event(
    controller: TransferController,
    event_type: type[Any],
    predicate: Callable[[Any], bool] = lambda _event: True,
    timeout: float = 3.0,
) -> Any:
    """Wait until the controller emits a matching event."""

    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"Timed out waiting for {event_type.__name__}")
        try:
            event = controller.events.get(timeout=remaining)
        except Empty as error:
            raise AssertionError(
                f"Timed out waiting for {event_type.__name__}"
            ) from error
        if isinstance(event, event_type) and predicate(event):
            return event


def test_progress_estimator_throttles_updates_and_reports_eta_then_stall() -> None:
    """Progress uses a rolling rate and suppresses ETA when transfer stalls."""

    now = [0.0]
    estimator = ProgressEstimator("job-1", 1024 * 1024, clock=lambda: now[0])

    assert estimator.record(0) is not None
    now[0] = 0.1
    assert estimator.record(128 * 1024) is None
    now[0] = 1.1
    progress = estimator.record(512 * 1024)

    assert progress is not None
    assert progress.transferred_bytes == 512 * 1024
    assert progress.bytes_per_second == pytest.approx((512 * 1024) / 1.1)
    assert progress.eta_seconds == pytest.approx(1.1)
    assert progress.is_stalled is False

    now[0] = 6.2
    stalled = estimator.stalled()
    assert stalled is not None
    assert stalled.is_stalled is True
    assert stalled.eta_seconds is None


def test_scp_backend_commits_via_unique_part_file_with_key_only_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful upload is visible only after its final rename."""

    source = tmp_path / "report.txt"
    source.write_bytes(b"proof of concept")
    remote_files: dict[str, bytes] = {}
    connector = _FakeConnector(_FakeConnection(remote_files))
    observed_destinations: list[str] = []

    async def fake_scp(
        source_path: Path,
        destination: tuple[_FakeConnection, str],
        **kwargs: object,
    ) -> None:
        connection, shell_path = destination
        observed_destinations.append(shell_path)
        remote_path = _raw_shell_path(shell_path)
        connection.files[remote_path] = source_path.read_bytes()
        progress = kwargs["progress_handler"]
        assert callable(progress)
        file_size = source.stat().st_size
        progress(b"report.txt", remote_path.encode(), file_size, file_size)

    monkeypatch.setattr("work_transfer_app.transfer.backend.asyncssh.scp", fake_scp)
    backend = ScpTransferBackend(connector=connector)
    job = TransferJob.create(source, "/srv/incoming", _config(tmp_path))

    result = asyncio.run(backend.transfer(job, lambda _progress: None))

    final_path = "/srv/incoming/report.txt"
    assert result.state is TransferState.COMPLETED
    assert remote_files == {final_path: source.read_bytes()}
    assert observed_destinations == [f"/srv/incoming/.report.txt.{job.id}.part"]
    assert connector.kwargs == {
        "host": "192.168.50.2",
        "port": 22,
        "username": "transfer",
        "client_keys": [str((tmp_path / "id_ed25519").resolve())],
        "known_hosts": str((tmp_path / "known_hosts").resolve()),
        "agent_path": None,
        "preferred_auth": "publickey",
        "host_based_auth": False,
        "kbdint_auth": False,
        "password_auth": False,
        "gss_auth": False,
        "gss_kex": False,
        "connect_timeout": 10,
    }


@pytest.mark.parametrize(
    "remote_directory",
    [
        "/srv/in coming",
        "/srv/incoming;touch PWN",
        "/srv/'single'\"double\"",
        "/srv/$(touch PWN)",
        "/srv/incoming>stolen",
    ],
)
def test_scp_backend_shell_quotes_hostile_remote_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_directory: str,
) -> None:
    """Only the SCP shell boundary receives quoting; SFTP keeps raw paths."""

    hostile_name = "report;$(touch LOCAL)>'\" data.txt"
    source = tmp_path / hostile_name
    source.write_bytes(b"safe payload")
    remote_files: dict[str, bytes] = {}
    connection = _FakeConnection(remote_files)
    observed_shell_paths: list[str] = []

    async def fake_scp(
        source_path: Path,
        destination: tuple[_FakeConnection, str],
        **_kwargs: object,
    ) -> None:
        remote_connection, shell_path = destination
        observed_shell_paths.append(shell_path)
        remote_connection.files[_raw_shell_path(shell_path)] = source_path.read_bytes()

    monkeypatch.setattr("work_transfer_app.transfer.backend.asyncssh.scp", fake_scp)
    backend = ScpTransferBackend(connector=_FakeConnector(connection))
    job = TransferJob.create(source, remote_directory, _config(tmp_path))

    result = asyncio.run(backend.transfer(job, lambda _progress: None))

    canonical_directory = posixpath.normpath(remote_directory)
    expected_final = posixpath.join(canonical_directory, hostile_name)
    expected_part = posixpath.join(
        canonical_directory, f".{hostile_name}.{job.id}.part"
    )
    assert result.state is TransferState.COMPLETED
    assert observed_shell_paths == [shlex.quote(expected_part)]
    assert remote_files == {expected_final: b"safe payload"}
    assert ("stat", expected_final) in connection.sftp.operations
    assert ("rename", expected_part, expected_final) in connection.sftp.operations


def test_scp_backend_resolves_tilde_before_all_remote_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tilde destinations resolve to one absolute directory without orphans."""

    source = tmp_path / "report.txt"
    source.write_bytes(b"payload")
    remote_files: dict[str, bytes] = {}
    connection = _FakeConnection(remote_files, home="/home/alice")
    observed_shell_paths: list[str] = []

    async def fake_scp(
        source_path: Path,
        destination: tuple[_FakeConnection, str],
        **_kwargs: object,
    ) -> None:
        remote_connection, shell_path = destination
        observed_shell_paths.append(shell_path)
        remote_connection.files[_raw_shell_path(shell_path)] = source_path.read_bytes()

    monkeypatch.setattr("work_transfer_app.transfer.backend.asyncssh.scp", fake_scp)
    backend = ScpTransferBackend(connector=_FakeConnector(connection))
    job = TransferJob.create(source, "~/incoming/../drop", _config(tmp_path))

    result = asyncio.run(backend.transfer(job, lambda _progress: None))

    expected_final = "/home/alice/drop/report.txt"
    expected_part = f"/home/alice/drop/.report.txt.{job.id}.part"
    assert result.state is TransferState.COMPLETED
    assert observed_shell_paths == [shlex.quote(expected_part)]
    assert remote_files == {expected_final: b"payload"}
    assert all(
        "~" not in item
        for operation in connection.sftp.operations
        for item in operation
    )


def test_scp_backend_abort_removes_partial_remote_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling an in-flight SCP leaves neither final nor staging output."""

    source = tmp_path / "large.bin"
    source.write_bytes(b"partial content")
    remote_files: dict[str, bytes] = {}
    connection = _FakeConnection(remote_files)
    connector = _FakeConnector(connection)

    async def scenario() -> TransferResult:
        """Start a partial upload and cancel only after staging begins."""

        upload_started = asyncio.Event()

        async def fake_scp(
            source_path: Path,
            destination: tuple[_FakeConnection, str],
            **_kwargs: object,
        ) -> None:
            remote_connection, shell_path = destination
            remote_path = _raw_shell_path(shell_path)
            remote_connection.files[remote_path] = source_path.read_bytes()[:4]
            upload_started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("work_transfer_app.transfer.backend.asyncssh.scp", fake_scp)
        backend = ScpTransferBackend(connector=connector)
        job = TransferJob.create(source, "/srv/incoming", _config(tmp_path))
        task = asyncio.create_task(backend.transfer(job, lambda _progress: None))
        await upload_started.wait()
        task.cancel()
        return await task

    result = asyncio.run(scenario())

    assert result.state is TransferState.ABORTED
    assert remote_files == {}


class _ScriptedBackend:
    """Drive single-transfer behavior without making network connections."""

    def __init__(self) -> None:
        self.started: list[str] = []

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Accept every connection config."""

        return ConnectionTestResult(config=config, is_success=True)

    async def transfer(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferProgress], None],
    ) -> TransferResult:
        """Block the first job until aborted and complete later jobs."""

        self.started.append(job.id)
        if len(self.started) == 1:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return TransferResult(job.id, TransferState.ABORTED)
        on_progress(
            TransferProgress(
                job_id=job.id,
                transferred_bytes=job.source.stat().st_size,
                total_bytes=job.source.stat().st_size,
                percent=100.0,
            )
        )
        return TransferResult(job.id, TransferState.COMPLETED)


def test_controller_rejects_second_transfer_until_active_transfer_aborts(
    tmp_path: Path,
) -> None:
    """One reserved active slot rejects overlap and reopens after cancellation."""

    backend = _ScriptedBackend()
    controller = TransferController(backend)
    try:
        connection = _config(tmp_path)
        test_result = controller.test_connection(connection).result(timeout=2)
        assert test_result.is_success is True
        _wait_for_event(controller, ConnectionTestedEvent)

        first_source = tmp_path / "first.bin"
        first_source.write_bytes(b"first")
        second_source = tmp_path / "second.bin"
        second_source.write_bytes(b"second")
        first = controller.start(first_source, "/srv/incoming")
        with pytest.raises(RuntimeError, match="^transfer_active$"):
            controller.start(second_source, "/srv/incoming")

        connecting = _wait_for_event(
            controller,
            TransferStateEvent,
            lambda event: (
                event.job_id == first.id and event.state is TransferState.CONNECTING
            ),
        )
        transferring = _wait_for_event(
            controller,
            TransferStateEvent,
            lambda event: (
                event.job_id == first.id and event.state is TransferState.TRANSFERRING
            ),
        )
        assert controller.abort() is True
        cancelling = _wait_for_event(
            controller,
            TransferStateEvent,
            lambda event: (
                event.job_id == first.id and event.state is TransferState.CANCELLING
            ),
        )

        aborted = _wait_for_event(
            controller,
            TransferFinishedEvent,
            lambda event: event.result.job_id == first.id,
        )
        second = controller.start(second_source, "/srv/incoming")
        completed = _wait_for_event(
            controller,
            TransferFinishedEvent,
            lambda event: event.result.job_id == second.id,
        )
        assert aborted.result.state is TransferState.ABORTED
        assert completed.result.state is TransferState.COMPLETED
        assert [connecting.state, transferring.state, cancelling.state] == [
            TransferState.CONNECTING,
            TransferState.TRANSFERRING,
            TransferState.CANCELLING,
        ]
        assert backend.started == [first.id, second.id]
    finally:
        controller.shutdown()


class _FailureBackend:
    """Return a caller-selected transfer failure without network access."""

    def __init__(self, error_kind: TransferErrorKind) -> None:
        self.error_kind = error_kind

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Accept every connection config."""

        return ConnectionTestResult(config=config, is_success=True)

    async def transfer(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferProgress], None],
    ) -> TransferResult:
        """Return the configured failure for one transfer."""

        del on_progress
        return TransferResult(
            job.id,
            TransferState.FAILED,
            "transfer failed",
            self.error_kind,
        )


@pytest.mark.parametrize(
    "error_kind",
    [
        TransferErrorKind.AUTHENTICATION,
        TransferErrorKind.HOST_KEY,
        TransferErrorKind.CONNECTION,
    ],
)
def test_connection_failure_degrades_and_invalidates_tested_connection(
    tmp_path: Path,
    error_kind: TransferErrorKind,
) -> None:
    """Connection-class transfer failures require a fresh connection test."""

    backend = _FailureBackend(error_kind)
    controller = TransferController(backend)
    try:
        connection = _config(tmp_path)
        controller.test_connection(connection).result(timeout=2)
        _wait_for_event(controller, ConnectionTestedEvent)
        source = tmp_path / "update.bin"
        source.write_bytes(b"update")
        job = controller.start(source, "/srv/incoming")

        finished = _wait_for_event(
            controller,
            TransferFinishedEvent,
            lambda event: event.result.job_id == job.id,
        )
        degraded = _wait_for_event(controller, ConnectionDegradedEvent)

        assert finished.result.state is TransferState.FAILED
        assert degraded.reason == "transfer failed"
        assert degraded.error_kind is error_kind
        assert controller.tested_connection is None
        with pytest.raises(RuntimeError, match="^connection_not_tested$"):
            controller.start(source, "/srv/incoming")
    finally:
        controller.shutdown()


def test_file_failure_preserves_tested_connection_for_next_transfer(
    tmp_path: Path,
) -> None:
    """A remote file failure does not degrade an otherwise valid connection."""

    connection = _config(tmp_path)
    controller = TransferController(_FailureBackend(TransferErrorKind.FILE))
    try:
        controller.test_connection(connection).result(timeout=2)
        _wait_for_event(controller, ConnectionTestedEvent)
        source = tmp_path / "update.bin"
        source.write_bytes(b"update")
        controller.start(source, "/srv/incoming")

        _wait_for_event(controller, TransferFinishedEvent)

        assert controller.tested_connection == connection
        with pytest.raises(Empty):
            controller.events.get_nowait()
    finally:
        controller.shutdown()


class _DelayedTestBackend:
    """Release connection tests in a caller-selected order."""

    def __init__(self, hosts: tuple[str, ...]) -> None:
        self.started = {host: threading.Event() for host in hosts}
        self.release = {host: threading.Event() for host in hosts}

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Wait for the test-controlled release associated with this host."""

        self.started[config.host].set()
        await asyncio.to_thread(self.release[config.host].wait)
        return ConnectionTestResult(config=config, is_success=True)

    async def transfer(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferProgress], None],
    ) -> TransferResult:
        """Complete transfers; these tests exercise connection state only."""

        del on_progress
        return TransferResult(job.id, TransferState.COMPLETED)


class _InterleavedFailureBackend:
    """Fail an old transfer while a newer connection test remains in flight."""

    def __init__(self, delayed_host: str) -> None:
        self.delayed_host = delayed_host
        self.transfer_started = threading.Event()
        self.release_transfer = threading.Event()
        self.connection_test_started = threading.Event()
        self.release_connection_test = threading.Event()

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Delay only the newer host's connection test."""

        if config.host == self.delayed_host:
            self.connection_test_started.set()
            await asyncio.to_thread(self.release_connection_test.wait)
        return ConnectionTestResult(config=config, is_success=True)

    async def transfer(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferProgress], None],
    ) -> TransferResult:
        """Release one connection failure at the test-selected time."""

        del on_progress
        self.transfer_started.set()
        await asyncio.to_thread(self.release_transfer.wait)
        return TransferResult(
            job.id,
            TransferState.FAILED,
            "old connection lost",
            TransferErrorKind.CONNECTION,
        )


def test_newer_connection_test_makes_older_completion_stale(tmp_path: Path) -> None:
    """An out-of-order older success cannot replace or reopen the latest config."""

    first = _config(tmp_path, host="first.example")
    second = _config(tmp_path, host="second.example")
    backend = _DelayedTestBackend((first.host, second.host))
    controller = TransferController(backend)
    try:
        first_future = controller.test_connection(first)
        assert backend.started[first.host].wait(timeout=2)
        second_future = controller.test_connection(second)
        assert backend.started[second.host].wait(timeout=2)

        backend.release[second.host].set()
        current = second_future.result(timeout=2)
        current_event = _wait_for_event(controller, ConnectionTestedEvent)
        backend.release[first.host].set()
        stale = first_future.result(timeout=2)

        assert current.is_success is True
        assert current_event.result.config == second
        assert stale.is_success is False
        assert stale.is_stale is True
        assert controller.tested_connection == second
        with pytest.raises(Empty):
            controller.events.get_nowait()
    finally:
        controller.shutdown()


def test_invalidation_makes_inflight_connection_completion_stale(
    tmp_path: Path,
) -> None:
    """Editing connection fields invalidates a test already in flight."""

    config = _config(tmp_path, host="pending.example")
    backend = _DelayedTestBackend((config.host,))
    controller = TransferController(backend)
    try:
        future = controller.test_connection(config)
        assert backend.started[config.host].wait(timeout=2)
        controller.invalidate_connection()
        backend.release[config.host].set()

        invalidated = _wait_for_event(controller, ConnectionTestedEvent)
        stale = future.result(timeout=2)

        assert invalidated.result.is_success is False
        assert invalidated.result.message == "connection_invalidated"
        assert stale.is_success is False
        assert stale.is_stale is True
        assert controller.tested_connection is None
        with pytest.raises(Empty):
            controller.events.get_nowait()
    finally:
        controller.shutdown()


def test_invalidation_supersedes_buffered_connection_success(tmp_path: Path) -> None:
    """A later invalidation event leaves observers disconnected after draining."""

    config = _config(tmp_path)
    controller = TransferController(_FailureBackend(TransferErrorKind.FILE))
    try:
        assert controller.test_connection(config).result(timeout=2).is_success is True
        controller.invalidate_connection()

        connected = _wait_for_event(controller, ConnectionTestedEvent)
        invalidated = _wait_for_event(controller, ConnectionTestedEvent)

        assert connected.result.is_success is True
        assert invalidated.result.is_success is False
        assert invalidated.result.message == "connection_invalidated"
        assert controller.tested_connection is None
    finally:
        controller.shutdown()


def test_old_transfer_failure_does_not_stale_new_connection_test(
    tmp_path: Path,
) -> None:
    """A failed old snapshot cannot invalidate a newer in-flight destination test."""

    old_config = _config(tmp_path, host="old.example")
    new_config = _config(tmp_path, host="new.example")
    backend = _InterleavedFailureBackend(new_config.host)
    controller = TransferController(backend)
    try:
        controller.test_connection(old_config).result(timeout=2)
        _wait_for_event(controller, ConnectionTestedEvent)
        source = tmp_path / "update.bin"
        source.write_bytes(b"update")
        controller.start(source, "/srv/incoming")
        assert backend.transfer_started.wait(timeout=2)

        new_test = controller.test_connection(new_config)
        assert backend.connection_test_started.wait(timeout=2)
        backend.release_transfer.set()
        _wait_for_event(controller, TransferFinishedEvent)
        with pytest.raises(Empty):
            controller.events.get_nowait()

        backend.release_connection_test.set()
        result = new_test.result(timeout=2)
        tested = _wait_for_event(controller, ConnectionTestedEvent)

        assert result.is_success is True
        assert result.is_stale is False
        assert tested.result.config == new_config
        assert controller.tested_connection == new_config
    finally:
        backend.release_transfer.set()
        backend.release_connection_test.set()
        controller.shutdown()


def test_shutdown_cancels_active_transfer_and_closes_control_api(
    tmp_path: Path,
) -> None:
    """Shutdown publishes the cancelled outcome and rejects later control work."""

    controller = TransferController(_ScriptedBackend())
    connection = _config(tmp_path)
    controller.test_connection(connection).result(timeout=2)
    _wait_for_event(controller, ConnectionTestedEvent)
    source = tmp_path / "large.bin"
    source.write_bytes(b"large")
    job = controller.start(source, "/srv/incoming")
    _wait_for_event(
        controller,
        TransferStateEvent,
        lambda event: (
            event.job_id == job.id and event.state is TransferState.TRANSFERRING
        ),
    )

    controller.shutdown()

    finished = _wait_for_event(controller, TransferFinishedEvent)
    assert finished.result.state is TransferState.ABORTED
    with pytest.raises(RuntimeError, match="^controller_closed$"):
        controller.abort()


class _DelayedCleanupBackend:
    """Hold cancellation cleanup until the test explicitly releases it."""

    def __init__(self) -> None:
        self.cleanup_started = threading.Event()
        self.release_cleanup = threading.Event()
        self.cleanup_finished = threading.Event()

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Accept the supplied connection snapshot."""

        return ConnectionTestResult(config, True)

    async def transfer(
        self,
        job: TransferJob,
        on_progress: Callable[[TransferProgress], None],
    ) -> TransferResult:
        """Model remote cleanup which outlives the first shutdown timeout."""

        _ = on_progress
        try:
            await asyncio.Event().wait()
            raise AssertionError("Blocking test transfer unexpectedly returned")
        except asyncio.CancelledError:
            self.cleanup_started.set()
            while not self.release_cleanup.is_set():
                await asyncio.sleep(0.01)
            self.cleanup_finished.set()
            return TransferResult(job.id, TransferState.ABORTED)


def test_shutdown_timeout_keeps_cleanup_running_until_a_later_close(
    tmp_path: Path,
) -> None:
    """A close timeout must not stop remote partial-file cleanup."""

    backend = _DelayedCleanupBackend()
    controller = TransferController(backend)
    try:
        connection = _config(tmp_path)
        controller.test_connection(connection).result(timeout=2)
        _wait_for_event(controller, ConnectionTestedEvent)
        source = tmp_path / "large.bin"
        source.write_bytes(b"large")
        job = controller.start(source, "/srv/incoming")
        _wait_for_event(
            controller,
            TransferStateEvent,
            lambda event: (
                event.job_id == job.id and event.state is TransferState.TRANSFERRING
            ),
        )

        with pytest.raises(TimeoutError, match="^shutdown_cleanup_timeout$"):
            controller.shutdown(timeout=0.02)
        assert backend.cleanup_started.wait(timeout=1)
        assert backend.cleanup_finished.is_set() is False

        backend.release_cleanup.set()
        controller.shutdown(timeout=1)

        assert backend.cleanup_finished.is_set() is True
        finished = _wait_for_event(controller, TransferFinishedEvent)
        assert finished.result.state is TransferState.ABORTED
    finally:
        backend.release_cleanup.set()
        controller.shutdown()
