"""Progress callback protocol for scraper to Telegram updates."""

from enum import Enum
from typing import Protocol, runtime_checkable, Optional
from dataclasses import dataclass


class ProgressStage(Enum):
    """Stages of the scraping process."""

    LOGIN_START = "login_start"
    OTP_SENT = "otp_sent"
    LOGIN_COMPLETE = "login_complete"
    FINDING_POLICIES = "finding_policies"
    DOWNLOAD_START = "download_start"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETE = "download_complete"
    ERROR = "error"


@dataclass
class ProgressInfo:
    """Progress information container."""

    stage: ProgressStage
    message: Optional[str] = None
    current: Optional[int] = None
    total: Optional[int] = None
    error: Optional[Exception] = None


@runtime_checkable
class ProgressCallback(Protocol):
    """Protocol for progress callback functions."""

    async def __call__(
        self,
        stage: ProgressStage,
        message: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
        error: Optional[Exception] = None
    ) -> None:
        """
        Report progress to the caller.

        Args:
            stage: Current stage of the process
            message: Optional message describing the progress
            current: Current item number (for progress tracking)
            total: Total number of items (for progress tracking)
            error: Exception if an error occurred
        """
        ...


async def noop_callback(
    stage: ProgressStage,
    message: Optional[str] = None,
    current: Optional[int] = None,
    total: Optional[int] = None,
    error: Optional[Exception] = None
) -> None:
    """Default no-op callback that does nothing."""
    pass
