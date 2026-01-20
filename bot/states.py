"""Conversation states for Phoenix Telegram Bot."""

from enum import IntEnum, auto


class ConversationState(IntEnum):
    """States for the login conversation flow."""

    AWAITING_ID = auto()
    AWAITING_PHONE = auto()
    AWAITING_OTP = auto()
    DOWNLOADING = auto()
    READY = auto()


# Timeout for conversation (return to start after inactivity)
CONVERSATION_TIMEOUT = 600  # 10 minutes
