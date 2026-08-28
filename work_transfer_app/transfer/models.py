"""Immutable data exchanged by transfer backends, controllers, and UI code."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from uuid import uuid4


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
    """One source file and the tested connection snapshot used to send it."""

    id: str
    source: Path
    remote_directory: str
    connection: ConnectionConfig

    def __post_init__(self) -> None:
        """Normalize paths and reject remote path control characters."""

        source = self.source.expanduser().resolve()
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
        """Create a job with a collision-resistant identifier."""

        return cls(uuid4().hex, source, remote_directory, connection)

    @property
    def final_remote_path(self) -> str:
        """Return the final remote pathname for this job."""

        return str(PurePosixPath(self.remote_directory) / self.source.name)

    @property
    def temporary_remote_path(self) -> str:
        """Return the unique same-directory staging pathname for this job."""

        temporary_name = f".{self.source.name}.{self.id}.part"
        return str(PurePosixPath(self.remote_directory) / temporary_name)


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
