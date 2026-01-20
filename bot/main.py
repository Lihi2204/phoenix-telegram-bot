"""Main entry point for Phoenix Insurance Telegram Bot."""

import asyncio
import logging
import sys
from pathlib import Path

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters
)

from config import settings
from database.db import Database
from gemini.file_search import GeminiFileSearch
from gemini.chat import GeminiChat
from bot.handlers import BotHandlers

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Initialize database after application starts."""
    db: Database = application.bot_data['db']
    await db.init_db()
    logger.info("Database initialized")


async def post_shutdown(application: Application):
    """Cleanup on shutdown."""
    logger.info("Shutting down...")

    # Cleanup Gemini clients
    gemini_fs: GeminiFileSearch = application.bot_data.get('gemini_fs')
    gemini_chat: GeminiChat = application.bot_data.get('gemini_chat')

    if gemini_fs:
        gemini_fs.close()
    if gemini_chat:
        gemini_chat.close()

    logger.info("Shutdown complete")


def main():
    """Start the bot."""
    # Validate configuration
    missing = settings.validate()
    if missing:
        logger.error(f"Missing required configuration: {', '.join(missing)}")
        logger.error("Please set these in your .env file")
        sys.exit(1)

    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Data directory: {settings.data_dir.absolute()}")

    # Initialize components
    db = Database(str(settings.database_path))
    gemini_fs = GeminiFileSearch(settings.gemini_api_key)
    gemini_chat = GeminiChat(settings.gemini_api_key, settings.gemini_model)

    logger.info("Components initialized")

    # Build application
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Store shared resources in bot_data
    application.bot_data['db'] = db
    application.bot_data['gemini_fs'] = gemini_fs
    application.bot_data['gemini_chat'] = gemini_chat

    # Initialize handlers
    handlers = BotHandlers(db, gemini_fs, gemini_chat)

    # Register handlers (order matters!)

    # 1. Conversation handler for login flow (must be first to catch /start)
    application.add_handler(handlers.get_conversation_handler())

    # 2. Other command handlers
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(CommandHandler("logout", handlers.logout_command))
    application.add_handler(CommandHandler("help", handlers.help_command))

    # 3. Question handler (catch-all for text when not in conversation)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers.handle_question
        )
    )

    # 4. Error handler
    application.add_error_handler(handlers.error_handler)

    # Start the bot
    logger.info("Starting Phoenix Insurance Telegram Bot...")
    logger.info(f"Model: {settings.gemini_model}")
    logger.info(f"Headless mode: {settings.headless}")

    application.run_polling(
        allowed_updates=["message"],
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
