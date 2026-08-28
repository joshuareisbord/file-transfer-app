"""Data exchanged by transfer backends, controllers, and UI code."""

from __future__ import annotations

import os
import stat
import threading
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import uuid4


class _PinnedSourceFile:
    """Own one regular-file descriptor from transfer start through cleanup."""

    __slots__ = ("_descriptor", "_descriptor_root", "_lock", "size")

    def __init__(self, source: Path) -> None:
        """Open and validate the selected source without an asynchronous race."""

        self._descriptor = -1
        self._descriptor_root = Path()
        self._lock = threading.Lock()
        self.size = 0
        descriptor_root = next(
            (
                candidate
                for candidate in (Path("/proc/self/fd"), Path("/dev/fd"))
                if candidate.is_dir()
            ),
            None,
        )
        if descriptor_root is None:
            raise OSError("source_descriptor_unavailable")

        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(source, flags)
        self._descriptor = descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            self.close()
            raise OSError("source_file_missing")

        self._descriptor_root = descriptor_root
        self.size = metadata.st_size

    @property
    def transfer_path(self) -> Path:
        """Return the descriptor-backed path without resolving it to a pathname."""

        with self._lock:
            if self._descriptor < 0:
                raise RuntimeError("source_file_closed")
            return self._descriptor_root / str(self._descriptor)

    def close(self) -> None:
        """Close the descriptor exactly once, including after error paths."""

        with self._lock:
            descriptor = self._descriptor
            self._descriptor = -1
        if descriptor >= 0:
            os.close(descriptor)

    def __del__(self) -> None:
        """Provide a last-resort close if a caller abandons an unstarted job."""

        self.close()


class TransferState(StrEnum):
    """Lifecycle states for one transfer."""

    CONNECTING = "connecting"
    TRANSFERRING = "transferring"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class TransferErrorKind(StrEnum):
    """Stable failure categories used across the backend and interface."""

    NONE = "none"
    FILE = "file"
    AUTHENTICATION = "authentication"
    HOST_KEY = "host_key"
    CONNECTION = "connection"
    UNKNOWN = "unknown"

    @property
    def degrades_connection(self) -> bool:
        """Return whether this failure invalidates the tested connection."""

        return self in {
            TransferErrorKind.AUTHENTICATION,
            TransferErrorKind.HOST_KEY,
            TransferErrorKind.CONNECTION,
        }


@dataclass(frozen=True, slots=True)
class ConnectionConfig:
    """SSH settings whose value is snapshotted into every transfer."""

    host: str
    username: str
    identity_file: Path
    port: int = 22
    known_hosts: Path = Path("~/.ssh/known_hosts")

    def __post_init__(self) -> None:
        """Normalize scalar values while retaining immutable configuration."""

        host = self.host.strip()
        username = self.username.strip()
        if not host or host.startswith("-") or "\x00" in host:
            raise ValueError("invalid_host")
        if not username or any(character.isspace() for character in username):
            raise ValueError("invalid_username")
        if not 1 <= self.port <= 65535:
            raise ValueError("invalid_port")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "username", username)
        object.__setattr__(
            self, "identity_file", self.identity_file.expanduser().resolve()
        )
        object.__setattr__(self, "known_hosts", self.known_hosts.expanduser().resolve())


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """Outcome of validating and opening one SSH connection."""

    config: ConnectionConfig
    is_success: bool
    message: str = ""
    error_kind: TransferErrorKind = TransferErrorKind.NONE
    is_stale: bool = False


@dataclass(frozen=True, slots=True)
class TransferJob:
    """One pinned source file and tested connection snapshot used to send it."""

    id: str
    source: Path
    remote_directory: str
    connection: ConnectionConfig
    _source_handle: _PinnedSourceFile | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Normalize paths and reject remote path control characters."""

        source = self.source.expanduser().absolute()
        remote_directory = self.remote_directory.strip()
        if not remote_directory.startswith(("/", "~/")):
            raise ValueError("invalid_remote_directory")
        if any(character in remote_directory for character in ("\x00", "\n", "\r")):
            raise ValueError("invalid_remote_directory")
        normalized_directory = str(PurePosixPath(remote_directory))
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "remote_directory", normalized_directory)

    @classmethod
    def create(
        cls,
        source: Path,
        remote_directory: str,
        connection: ConnectionConfig,
    ) -> TransferJob:
        """Create a job while synchronously pinning the selected regular file."""

        normalized_source = source.expanduser().absolute()
        try:
            source_handle = _PinnedSourceFile(normalized_source)
        except OSError as error:
            raise ValueError("source_file_missing") from error
        try:
            return cls(
                uuid4().hex,
                normalized_source,
                remote_directory,
                connection,
                source_handle,
            )
        except Exception:
            source_handle.close()
            raise

    @property
    def source_size(self) -> int:
        """Return the captured size used for transfer progress estimation."""

        if self._source_handle is None:
            raise RuntimeError("source_file_not_pinned")
        return self._source_handle.size

    @property
    def source_for_transfer(self) -> Path:
        """Return the open descriptor path which SCP must read."""

        if self._source_handle is None:
            raise RuntimeError("source_file_not_pinned")
        return self._source_handle.transfer_path

    def close_source(self) -> None:
        """Release this job's pinned source descriptor idempotently."""

        if self._source_handle is not None:
            self._source_handle.close()


@dataclass(frozen=True, slots=True)
class TransferProgress:
    """Latest byte-level progress and rolling transfer estimate."""

    job_id: str
    transferred_bytes: int
    total_bytes: int
    percent: float
    bytes_per_second: float | None = None
    eta_seconds: float | None = None
    is_stalled: bool = False


@dataclass(frozen=True, slots=True)
class TransferResult:
    """Terminal outcome for one transfer job."""

    job_id: str
    state: TransferState
    message: str = ""
    error_kind: TransferErrorKind = TransferErrorKind.NONE

    @property
    def is_success(self) -> bool:
        """Return whether the job committed its final remote file."""

        return self.state is TransferState.COMPLETED


@dataclass(frozen=True, slots=True)
class ConnectionTestedEvent:
    """Notify observers that a connection test completed."""

    result: ConnectionTestResult


@dataclass(frozen=True, slots=True)
class TransferStateEvent:
    """Notify observers of a non-terminal job state transition."""

    job_id: str
    state: TransferState
    message: str = ""


@dataclass(frozen=True, slots=True)
class TransferProgressEvent:
    """Notify observers of throttled byte-level progress."""

    progress: TransferProgress


@dataclass(frozen=True, slots=True)
class TransferFinishedEvent:
    """Notify observers of one job's terminal outcome."""

    result: TransferResult


@dataclass(frozen=True, slots=True)
class ConnectionDegradedEvent:
    """Notify observers that a transfer invalidated the tested connection."""

    reason: str
    error_kind: TransferErrorKind


type TransferEvent = (
    ConnectionTestedEvent
    | TransferStateEvent
    | TransferProgressEvent
    | TransferFinishedEvent
    | ConnectionDegradedEvent
)
