"""Public transfer API for the desktop application."""

from work_transfer_app.transfer.backend import (
    ProgressCallback,
    ScpTransferBackend,
    TransferBackend,
)
from work_transfer_app.transfer.controller import TransferController
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

__all__ = [
    "ConnectionConfig",
    "ConnectionDegradedEvent",
    "ConnectionTestResult",
    "ConnectionTestedEvent",
    "ProgressCallback",
    "ScpTransferBackend",
    "TransferBackend",
    "TransferController",
    "TransferErrorKind",
    "TransferEvent",
    "TransferFinishedEvent",
    "TransferJob",
    "TransferProgress",
    "TransferProgressEvent",
    "TransferResult",
    "TransferState",
    "TransferStateEvent",
]
