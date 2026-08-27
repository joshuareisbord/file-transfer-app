"""Public transfer API for the desktop application."""

from work_transfer_app.transfer.backend import (
    ProgressCallback,
    ScpTransferBackend,
    TransferBackend,
)
from work_transfer_app.transfer.controller import TransferQueueController
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

__all__ = [
    "ConnectionConfig",
    "ConnectionTestResult",
    "ConnectionTestedEvent",
    "JobQueuedEvent",
    "JobRemovedEvent",
    "ProgressCallback",
    "QueuePausedEvent",
    "QueueResumedEvent",
    "ScpTransferBackend",
    "TransferBackend",
    "TransferErrorKind",
    "TransferEvent",
    "TransferFinishedEvent",
    "TransferJob",
    "TransferProgress",
    "TransferProgressEvent",
    "TransferQueueController",
    "TransferResult",
    "TransferState",
    "TransferStateEvent",
]
