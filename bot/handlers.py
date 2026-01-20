"""Telegram bot handlers for Phoenix Insurance Bot."""

import re
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters
)
from telegram.constants import ParseMode

from .states import ConversationState, CONVERSATION_TIMEOUT
from .messages import Messages
from database.db import Database
from database.models import UserState
from scraper.phoenix_downloader import PhoenixDownloader
from scraper.progress_callback import ProgressStage
from gemini.file_search import GeminiFileSearch
from gemini.chat import GeminiChat
from config import settings

logger = logging.getLogger(__name__)

# Validation patterns
ID_PATTERN = re.compile(r'^\d{9}$')
PHONE_PATTERN = re.compile(r'^05\d{8}$')
OTP_PATTERN = re.compile(r'^\d{6}$')


class BotHandlers:
    """Container for all Telegram bot handlers."""

    def __init__(
        self,
        db: Database,
        gemini_fs: GeminiFileSearch,
        gemini_chat: GeminiChat
    ):
        """
        Initialize handlers with required services.

        Args:
            db: Database instance
            gemini_fs: Gemini File Search instance
            gemini_chat: Gemini Chat instance
        """
        self.db = db
        self.gemini_fs = gemini_fs
        self.gemini_chat = gemini_chat

    def _get_user_dir(self, telegram_id: int) -> Path:
        """Get user's data directory."""
        return settings.data_dir / str(telegram_id)

    async def _cleanup_scraper(self, context: ContextTypes.DEFAULT_TYPE):
        """Cleanup any active scraper in context."""
        scraper: Optional[PhoenixDownloader] = context.user_data.get('scraper')
        if scraper:
            try:
                scraper.cancel()
                await scraper.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error cleaning up scraper: {e}")
            finally:
                context.user_data.pop('scraper', None)

    def _create_progress_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Create progress callback that sends messages to the chat."""
        async def callback(
            stage: ProgressStage,
            message: str = None,
            current: int = None,
            total: int = None,
            error: Exception = None
        ):
            try:
                if stage == ProgressStage.FINDING_POLICIES:
                    await update.message.reply_text(Messages.DOWNLOADING_POLICIES)
                elif stage == ProgressStage.DOWNLOAD_START:
                    text = message or Messages.DOWNLOADING_START
                    await update.message.reply_text(text)
                elif stage == ProgressStage.DOWNLOAD_PROGRESS and current and total:
                    # Only send every few updates to avoid spam
                    if current == 1 or current == total or current % 3 == 0:
                        text = Messages.DOWNLOADING_PROGRESS.format(current=current, total=total)
                        await update.message.reply_text(text)
                elif stage == ProgressStage.DOWNLOAD_COMPLETE:
                    pass  # Will be handled by main flow
                elif stage == ProgressStage.ERROR and error:
                    logger.error(f"Scraper error: {error}")
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")

        return callback

    # ==================== Command Handlers ====================

    async def start_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle /start - begin login flow."""
        telegram_id = update.effective_user.id
        logger.info(f"User {telegram_id} started bot")

        # Check if already connected
        user = await self.db.get_user(telegram_id)
        if user and user.state == UserState.READY and user.gemini_store_name:
            await update.message.reply_text(Messages.ALREADY_CONNECTED)
            return ConversationHandler.END

        # Check if in progress
        if user and user.state in [UserState.DOWNLOADING, UserState.UPLOADING]:
            await update.message.reply_text(Messages.STATUS_IN_PROGRESS)
            return ConversationHandler.END

        # Cleanup any existing scraper
        await self._cleanup_scraper(context)

        # Start fresh login
        await self.db.upsert_user(telegram_id, state=UserState.AWAITING_ID)
        await update.message.reply_text(Messages.WELCOME)
        return ConversationState.AWAITING_ID

    async def status_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /status command."""
        telegram_id = update.effective_user.id
        user = await self.db.get_user(telegram_id)

        if not user or user.state == UserState.IDLE:
            await update.message.reply_text(Messages.STATUS_NOT_CONNECTED)
            return

        if user.state in [UserState.DOWNLOADING, UserState.UPLOADING]:
            await update.message.reply_text(Messages.STATUS_IN_PROGRESS)
            return

        if user.state == UserState.READY and user.gemini_store_name:
            # Mask ID for privacy (show only last 4 digits)
            masked_id = f"*****{user.phoenix_id[-4:]}" if user.phoenix_id else "לא ידוע"
            last_update = (
                user.updated_at.strftime("%d/%m/%Y %H:%M")
                if user.updated_at else "לא ידוע"
            )

            # Get document count
            user_dir = self._get_user_dir(telegram_id)
            doc_count = len(list(user_dir.glob("**/*.pdf"))) if user_dir.exists() else 0

            await update.message.reply_text(
                Messages.STATUS_CONNECTED.format(
                    masked_id=masked_id,
                    last_update=last_update,
                    doc_count=doc_count
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(Messages.STATUS_NOT_CONNECTED)

    async def logout_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /logout - cleanup and disconnect."""
        telegram_id = update.effective_user.id
        logger.info(f"User {telegram_id} logging out")

        # Cleanup scraper if active
        await self._cleanup_scraper(context)

        user = await self.db.get_user(telegram_id)

        if user:
            # Delete Gemini store
            if user.gemini_store_name:
                try:
                    await self.gemini_fs.delete_store(user.gemini_store_name)
                except Exception as e:
                    logger.error(f"Error deleting Gemini store: {e}")

            # Delete local files
            user_dir = self._get_user_dir(telegram_id)
            if user_dir.exists():
                try:
                    shutil.rmtree(user_dir)
                except Exception as e:
                    logger.error(f"Error deleting user files: {e}")

            # Reset user state
            await self.db.reset_user(telegram_id)

        await update.message.reply_text(Messages.LOGOUT_SUCCESS)

    async def refresh_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle /refresh - re-download documents."""
        telegram_id = update.effective_user.id
        user = await self.db.get_user(telegram_id)

        if not user or user.state != UserState.READY:
            await update.message.reply_text(Messages.NOT_READY)
            return ConversationHandler.END

        await update.message.reply_text(Messages.REFRESH_STARTED)

        # Delete old Gemini store
        if user.gemini_store_name:
            try:
                await self.gemini_fs.delete_store(user.gemini_store_name)
            except Exception as e:
                logger.error(f"Error deleting old Gemini store: {e}")

        # Delete local files
        user_dir = self._get_user_dir(telegram_id)
        if user_dir.exists():
            try:
                shutil.rmtree(user_dir)
            except Exception as e:
                logger.error(f"Error deleting user files: {e}")

        # Reset to login state
        await self.db.upsert_user(
            telegram_id,
            state=UserState.AWAITING_ID,
            gemini_store_name=None,
            documents_count=0
        )

        await update.message.reply_text(Messages.ASK_ID)
        return ConversationState.AWAITING_ID

    async def help_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle /help command."""
        await update.message.reply_text(Messages.HELP, parse_mode=ParseMode.MARKDOWN)

    async def cancel_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle /cancel during conversation."""
        await self._cleanup_scraper(context)
        await update.message.reply_text(Messages.CANCELLED)
        return ConversationHandler.END

    # ==================== Conversation Handlers ====================

    async def receive_id(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle ID input."""
        text = update.message.text.strip()
        telegram_id = update.effective_user.id

        if not ID_PATTERN.match(text):
            await update.message.reply_text(Messages.INVALID_ID)
            return ConversationState.AWAITING_ID

        # Store ID temporarily
        context.user_data['phoenix_id'] = text
        await self.db.upsert_user(
            telegram_id,
            phoenix_id=text,
            state=UserState.AWAITING_PHONE
        )

        await update.message.reply_text(Messages.ASK_PHONE)
        return ConversationState.AWAITING_PHONE

    async def receive_phone(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle phone input and initiate OTP."""
        text = update.message.text.strip()
        telegram_id = update.effective_user.id

        if not PHONE_PATTERN.match(text):
            await update.message.reply_text(Messages.INVALID_PHONE)
            return ConversationState.AWAITING_PHONE

        phoenix_id = context.user_data.get('phoenix_id')
        if not phoenix_id:
            await update.message.reply_text(Messages.OTP_EXPIRED)
            return ConversationHandler.END

        await update.message.reply_text(Messages.SENDING_OTP)

        # Create download directory
        user_dir = self._get_user_dir(telegram_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        # Initialize scraper and start login
        scraper = PhoenixDownloader(
            user_id=phoenix_id,
            phone=text,
            download_dir=user_dir,
            headless=settings.headless
        )

        try:
            # Enter context manager and store for later
            await scraper.__aenter__()
            context.user_data['scraper'] = scraper
            context.user_data['phone'] = text

            # Initiate login (sends OTP)
            success = await scraper.initiate_login()

            if success:
                await self.db.upsert_user(
                    telegram_id,
                    phone_number=text,
                    state=UserState.AWAITING_OTP
                )
                await update.message.reply_text(Messages.ASK_OTP)
                return ConversationState.AWAITING_OTP
            else:
                # Cleanup on failure
                await self._cleanup_scraper(context)
                await update.message.reply_text(Messages.LOGIN_FAILED)
                return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error initiating login: {e}")
            await self._cleanup_scraper(context)
            await update.message.reply_text(Messages.LOGIN_FAILED)
            return ConversationHandler.END

    async def receive_otp(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle OTP input and complete login."""
        text = update.message.text.strip()
        telegram_id = update.effective_user.id

        if not OTP_PATTERN.match(text):
            await update.message.reply_text(Messages.INVALID_OTP)
            return ConversationState.AWAITING_OTP

        scraper: Optional[PhoenixDownloader] = context.user_data.get('scraper')
        if not scraper:
            await update.message.reply_text(Messages.OTP_EXPIRED)
            return ConversationHandler.END

        await update.message.reply_text(Messages.CONNECTING)

        try:
            # Complete login with OTP
            success = await scraper.complete_login(text)

            if not success:
                await self._cleanup_scraper(context)
                await update.message.reply_text(Messages.LOGIN_FAILED)
                return ConversationHandler.END

            await update.message.reply_text(Messages.LOGIN_SUCCESS)
            await self.db.upsert_user(telegram_id, state=UserState.DOWNLOADING)

            # Setup progress callback
            progress_cb = self._create_progress_callback(update, context)
            scraper.progress = progress_cb

            # Download documents
            pdf_paths = await scraper.download_health_documents()

            # Cleanup scraper - we're done with the browser
            await self._cleanup_scraper(context)

            if not pdf_paths:
                await self.db.upsert_user(telegram_id, state=UserState.IDLE)
                await update.message.reply_text(Messages.NO_POLICIES)
                return ConversationHandler.END

            await update.message.reply_text(
                Messages.DOWNLOADING_COMPLETE.format(count=len(pdf_paths))
            )

            # Create Gemini store and upload
            await self.db.upsert_user(telegram_id, state=UserState.UPLOADING)
            await update.message.reply_text(Messages.UPLOADING_START)

            # Create File Search store
            store_name = await self.gemini_fs.create_store(telegram_id)

            # Upload documents with progress
            async def upload_progress(current: int, total: int):
                if current == 1 or current == total or current % 5 == 0:
                    await update.message.reply_text(
                        Messages.UPLOADING_PROGRESS.format(current=current, total=total)
                    )

            uploaded_count = await self.gemini_fs.upload_documents(
                store_name,
                pdf_paths,
                progress_callback=upload_progress
            )

            # Get policies count
            policies_count = len(set(p.parent.parent.name for p in pdf_paths))

            # Save final state
            await self.db.upsert_user(
                telegram_id,
                state=UserState.READY,
                gemini_store_name=store_name,
                documents_count=uploaded_count,
                last_download=datetime.utcnow()
            )

            await update.message.reply_text(
                Messages.READY.format(
                    documents=uploaded_count,
                    policies=policies_count
                ),
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error in OTP handling: {e}")
            await self._cleanup_scraper(context)
            await self.db.upsert_user(telegram_id, state=UserState.IDLE)
            await update.message.reply_text(Messages.DOWNLOAD_FAILED)
            return ConversationHandler.END

    # ==================== Question Handler ====================

    async def handle_question(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Handle user questions about their policies."""
        telegram_id = update.effective_user.id
        user = await self.db.get_user(telegram_id)

        if not user or user.state != UserState.READY or not user.gemini_store_name:
            await update.message.reply_text(Messages.NOT_READY)
            return

        # Show thinking indicator
        await update.message.reply_text(Messages.THINKING)

        # Query Gemini
        response = await self.gemini_chat.query(
            question=update.message.text,
            store_name=user.gemini_store_name
        )

        await update.message.reply_text(response)

    # ==================== Timeout Handler ====================

    async def timeout_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle conversation timeout."""
        await self._cleanup_scraper(context)

        if update and update.message:
            await update.message.reply_text(Messages.OTP_EXPIRED)

        return ConversationHandler.END

    # ==================== Error Handler ====================

    async def error_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ):
        """Global error handler for uncaught exceptions."""
        logger.error(f"Exception while handling update: {context.error}")

        # Cleanup any active scraper session
        await self._cleanup_scraper(context)

        # Notify user
        if update and update.effective_message:
            try:
                await update.effective_message.reply_text(Messages.ERROR_GENERAL)
            except Exception:
                pass

    # ==================== Build Handlers ====================

    def get_conversation_handler(self) -> ConversationHandler:
        """Build and return the conversation handler."""
        return ConversationHandler(
            entry_points=[
                CommandHandler("start", self.start_command),
                CommandHandler("refresh", self.refresh_command)
            ],
            states={
                ConversationState.AWAITING_ID: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.receive_id
                    )
                ],
                ConversationState.AWAITING_PHONE: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.receive_phone
                    )
                ],
                ConversationState.AWAITING_OTP: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.receive_otp
                    )
                ],
                ConversationHandler.TIMEOUT: [
                    MessageHandler(filters.ALL, self.timeout_handler)
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_command),
                CommandHandler("help", self.help_command)
            ],
            conversation_timeout=CONVERSATION_TIMEOUT,
            name="login_conversation",
            persistent=False
        )
