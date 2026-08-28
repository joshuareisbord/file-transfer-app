"""AsyncSSH transfer backend with safe temporary-file commit semantics."""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Callable
from contextlib import suppress
from pathlib import PurePosixPath
from typing import Protocol, Self, cast

import asyncssh

from work_transfer_app.transfer.models import (
    ConnectionConfig,
    ConnectionTestResult,
    TransferErrorKind,
    TransferJob,
    TransferProgress,
    TransferResult,
    TransferState,
)
from work_transfer_app.transfer.progress import ProgressEstimator

ProgressCallback = Callable[[TransferProgress], None]


class TransferBackend(Protocol):
    """Backend contract consumed by the single-transfer controller."""

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Validate credentials and establish a connection once."""

        ...

    async def transfer(
        self, job: TransferJob, on_progress: ProgressCallback
    ) -> TransferResult:
        """Transfer one job and report a terminal result."""

        ...


class _SftpOperations(Protocol):
    """Subset of AsyncSSH SFTP operations required for safe commits."""

    async def stat(self, path: str) -> object:
        """Read attributes for a remote path."""

        ...

    async def rename(self, source: str, destination: str) -> None:
        """Rename a remote path without requesting overwrite semantics."""

        ...

    async def remove(self, path: str) -> None:
        """Remove a remote path."""

        ...

    async def realpath(self, path: str) -> str:
        """Resolve a remote path to its absolute canonical form."""

        ...


class _SftpContext(Protocol):
    """Asynchronous SFTP context returned by an SSH connection."""

    async def __aenter__(self) -> _SftpOperations:
        """Open the SFTP context."""

        ...

    async def __aexit__(self, *args: object) -> object:
        """Close the SFTP context."""

        ...


class _ConnectionContext(Protocol):
    """Connection operations shared by real and test SSH contexts."""

    async def __aenter__(self) -> Self:
        """Open the SSH context."""

        ...

    async def __aexit__(self, *args: object) -> object:
        """Close the SSH context."""

        ...

    def start_sftp_client(self) -> _SftpContext:
        """Start an SFTP client on this connection."""

        ...


class _Connector(Protocol):
    """Injectable constructor for an asynchronous SSH connection."""

    def __call__(self, host: str, port: int, **kwargs: object) -> _ConnectionContext:
        """Build an asynchronous SSH connection context."""

        ...


class _LocalConfigError(Exception):
    """Configuration failure with a stable transfer error category."""

    def __init__(self, message: str, error_kind: TransferErrorKind) -> None:
        """Retain a local error key and its transfer error category."""

        super().__init__(message)
        self.error_kind = error_kind


class ScpTransferBackend:
    """Transfer files with AsyncSSH SCP and commit them through SFTP."""

    def __init__(self, connector: _Connector | None = None) -> None:
        """Create a backend using AsyncSSH or an injected connector."""

        self._connector = connector or cast(_Connector, asyncssh.connect)

    async def test_connection(self, config: ConnectionConfig) -> ConnectionTestResult:
        """Open and close a strict host-verified, key-only SSH connection."""

        try:
            options = self._connection_options(config)
            async with self._connector(config.host, config.port, **options):
                pass
        except _LocalConfigError as error:
            return ConnectionTestResult(config, False, str(error), error.error_kind)
        except Exception as error:  # noqa: BLE001 - normalize boundary failures
            return ConnectionTestResult(
                config, False, self._message(error), self._error_kind(error)
            )
        return ConnectionTestResult(config, True)

    async def transfer(
        self, job: TransferJob, on_progress: ProgressCallback
    ) -> TransferResult:
        """Upload one file through a unique part path and commit on success."""

        if not job.source.is_file():
            return TransferResult(
                job.id,
                TransferState.FAILED,
                "source_file_missing",
                TransferErrorKind.FILE,
            )
        try:
            options = self._connection_options(job.connection)
            async with self._connector(
                job.connection.host, job.connection.port, **options
            ) as connection:
                return await self._transfer_connected(connection, job, on_progress)
        except asyncio.CancelledError:
            return TransferResult(job.id, TransferState.ABORTED)
        except _LocalConfigError as error:
            return TransferResult(
                job.id, TransferState.FAILED, str(error), error.error_kind
            )
        except Exception as error:  # noqa: BLE001 - normalize boundary failures
            return TransferResult(
                job.id,
                TransferState.FAILED,
                self._message(error),
                self._error_kind(error),
            )

    async def _transfer_connected(
        self,
        connection: _ConnectionContext,
        job: TransferJob,
        on_progress: ProgressCallback,
    ) -> TransferResult:
        """Run SCP and safe commit over one already-open connection."""

        async with connection.start_sftp_client() as sftp:
            remote_directory = await self._canonical_remote_directory(
                sftp, job.remote_directory
            )
            final_remote_path = str(PurePosixPath(remote_directory) / job.source.name)
            temporary_remote_path = str(
                PurePosixPath(remote_directory) / f".{job.source.name}.{job.id}.part"
            )
            if await self._remote_exists(sftp, final_remote_path):
                return TransferResult(
                    job.id,
                    TransferState.FAILED,
                    "destination_file_exists",
                    TransferErrorKind.FILE,
                )

            estimator = ProgressEstimator(job.id, job.source.stat().st_size)
            progress_signal = asyncio.Event()

            def handle_progress(
                _source: bytes,
                _destination: bytes,
                transferred_bytes: int,
                _total_bytes: int,
            ) -> None:
                """Translate AsyncSSH cumulative byte callbacks into UI events."""

                progress = estimator.record(transferred_bytes, _total_bytes)
                if progress is not None:
                    on_progress(progress)
                    progress_signal.set()

            try:
                transfer_task = asyncio.create_task(
                    asyncssh.scp(
                        job.source,
                        (
                            cast(asyncssh.SSHClientConnection, connection),
                            shlex.quote(temporary_remote_path),
                        ),
                        recurse=False,
                        preserve=False,
                        progress_handler=handle_progress,
                    )
                )
                monitor_task = asyncio.create_task(
                    self._monitor_stall(
                        transfer_task,
                        estimator,
                        progress_signal,
                        on_progress,
                    )
                )
                try:
                    await transfer_task
                finally:
                    monitor_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await monitor_task

                # Recheck immediately before a non-overwriting rename so another
                # writer cannot be silently replaced after the initial check.
                if await self._remote_exists(sftp, final_remote_path):
                    await self._remove_best_effort(sftp, temporary_remote_path)
                    return TransferResult(
                        job.id,
                        TransferState.FAILED,
                        "destination_file_exists",
                        TransferErrorKind.FILE,
                    )
                await sftp.rename(temporary_remote_path, final_remote_path)
            except asyncio.CancelledError:
                await self._remove_best_effort(sftp, temporary_remote_path)
                return TransferResult(job.id, TransferState.ABORTED)
            except Exception as error:  # noqa: BLE001 - normalize SCP failures
                await self._remove_best_effort(sftp, temporary_remote_path)
                return TransferResult(
                    job.id,
                    TransferState.FAILED,
                    self._message(error),
                    self._error_kind(error, connected=True),
                )

            on_progress(estimator.complete())
            return TransferResult(job.id, TransferState.COMPLETED)

    @staticmethod
    async def _monitor_stall(
        transfer_task: asyncio.Task[None],
        estimator: ProgressEstimator,
        progress_signal: asyncio.Event,
        on_progress: ProgressCallback,
    ) -> None:
        """Publish a stalled snapshot when no byte callback arrives for five seconds."""

        while not transfer_task.done():
            try:
                await asyncio.wait_for(progress_signal.wait(), timeout=0.25)
                progress_signal.clear()
            except TimeoutError:
                progress = estimator.stalled()
                if progress is not None:
                    on_progress(progress)

    @staticmethod
    async def _remote_exists(sftp: _SftpOperations, path: str) -> bool:
        """Return whether a remote path exists without masking other failures."""

        try:
            await sftp.stat(path)
        except asyncssh.SFTPNoSuchFile:
            return False
        return True

    @staticmethod
    async def _canonical_remote_directory(
        sftp: _SftpOperations, remote_directory: str
    ) -> str:
        """Resolve absolute and home-relative input once before deriving paths."""

        if remote_directory == "~" or remote_directory.startswith("~/"):
            home = await sftp.realpath(".")
            suffix = remote_directory[2:] if remote_directory.startswith("~/") else ""
            candidate = str(PurePosixPath(home) / suffix)
        else:
            candidate = remote_directory
        canonical = await sftp.realpath(candidate)
        if not canonical.startswith("/"):
            raise ValueError("remote_directory_not_absolute")
        return canonical

    @staticmethod
    async def _remove_best_effort(sftp: _SftpOperations, path: str) -> None:
        """Remove a staging file without obscuring the primary failure."""

        try:
            await sftp.remove(path)
        except Exception:  # noqa: BLE001 - cleanup must not mask primary error
            return

    @staticmethod
    def _connection_options(config: ConnectionConfig) -> dict[str, object]:
        """Build strict known-host and key-only AsyncSSH options."""

        if not config.identity_file.is_file():
            raise _LocalConfigError(
                "identity_file_missing", TransferErrorKind.AUTHENTICATION
            )
        if not config.known_hosts.is_file():
            raise _LocalConfigError("known_hosts_missing", TransferErrorKind.HOST_KEY)
        return {
            "username": config.username,
            "client_keys": [str(config.identity_file)],
            "known_hosts": str(config.known_hosts),
            "agent_path": None,
            "preferred_auth": "publickey",
            "host_based_auth": False,
            "kbdint_auth": False,
            "password_auth": False,
            "gss_auth": False,
            "gss_kex": False,
            "connect_timeout": 10,
        }

    @staticmethod
    def _error_kind(error: Exception, *, connected: bool = False) -> TransferErrorKind:
        """Map AsyncSSH and network errors to stable transfer behavior."""

        if isinstance(error, asyncssh.PermissionDenied):
            return TransferErrorKind.AUTHENTICATION
        if isinstance(error, asyncssh.HostKeyNotVerifiable):
            return TransferErrorKind.HOST_KEY
        if isinstance(error, asyncssh.SFTPError):
            return TransferErrorKind.FILE
        if isinstance(
            error,
            (
                asyncssh.ConnectionLost,
                asyncssh.DisconnectError,
                asyncssh.ChannelOpenError,
                ConnectionError,
                TimeoutError,
            ),
        ):
            return TransferErrorKind.CONNECTION
        if isinstance(error, OSError):
            return TransferErrorKind.FILE if connected else TransferErrorKind.CONNECTION
        if connected and isinstance(error, ValueError):
            return TransferErrorKind.FILE
        return TransferErrorKind.UNKNOWN

    @staticmethod
    def _message(error: Exception) -> str:
        """Return non-empty diagnostics while leaving localization to the UI."""

        return str(error).strip() or type(error).__name__
