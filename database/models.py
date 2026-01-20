"""Database models for Phoenix Telegram Bot."""

import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class UserState(enum.Enum):
    """User conversation states."""

    IDLE = "idle"
    AWAITING_ID = "awaiting_id"
    AWAITING_PHONE = "awaiting_phone"
    AWAITING_OTP = "awaiting_otp"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    READY = "ready"


class User(Base):
    """User model for storing Phoenix connection state."""

    __tablename__ = "users"

    telegram_id = Column(Integer, primary_key=True)
    phoenix_id = Column(String(9), nullable=True)  # Israeli ID (9 digits)
    phone_number = Column(String(10), nullable=True)  # Phone (05XXXXXXXX)
    state = Column(SQLEnum(UserState), default=UserState.IDLE)
    gemini_store_name = Column(String(255), nullable=True)  # Gemini File Search store
    documents_count = Column(Integer, default=0)
    last_download = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, state={self.state})>"
