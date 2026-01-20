"""Async database operations for Phoenix Telegram Bot."""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from .models import Base, User, UserState


class Database:
    """Async database manager using SQLAlchemy with aiosqlite."""

    def __init__(self, database_path: str):
        """Initialize database with path to SQLite file."""
        # Ensure directory exists
        db_dir = os.path.dirname(database_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self.database_url = f"sqlite+aiosqlite:///{database_path}"
        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            future=True
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def init_db(self):
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self):
        """Context manager for database sessions."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def get_user(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def upsert_user(self, telegram_id: int, **kwargs) -> User:
        """Create or update user with given fields."""
        async with self.session() as session:
            # Check if user exists
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user is None:
                # Create new user
                user = User(telegram_id=telegram_id, **kwargs)
                session.add(user)
            else:
                # Update existing user
                for key, value in kwargs.items():
                    if hasattr(user, key):
                        setattr(user, key, value)
                user.updated_at = datetime.utcnow()

            await session.commit()
            await session.refresh(user)
            return user

    async def delete_user(self, telegram_id: int) -> bool:
        """Delete user and return True if deleted."""
        async with self.session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user:
                await session.delete(user)
                await session.commit()
                return True
            return False

    async def reset_user(self, telegram_id: int) -> Optional[User]:
        """Reset user to initial state (keeping telegram_id only)."""
        return await self.upsert_user(
            telegram_id,
            phoenix_id=None,
            phone_number=None,
            state=UserState.IDLE,
            gemini_store_name=None,
            documents_count=0,
            last_download=None
        )
