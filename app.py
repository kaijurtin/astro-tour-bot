import os
import asyncio
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram.ext import Application
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from processors.telegram_handler import handle_message, handle_callback
from database import init_db

# Load environment variables first
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Config
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
UPLOADS_DIR = os.getenv('UPLOADS_DIR', '/mnt/nas/tour-inputs')
ASTRO_REPO = os.getenv('ASTRO_REPO', '/opt/astro')

# Ensure directories exist
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(f'{UPLOADS_DIR}/pending', exist_ok=True)
os.makedirs(f'{UPLOADS_DIR}/processed', exist_ok=True)

# Initialize database
init_db()


async def main():
    """Start the bot using polling"""
    if not TELEGRAM_TOKEN or 'your_' in TELEGRAM_TOKEN:
        logger.error('TELEGRAM_TOKEN not properly configured')
        raise ValueError("TELEGRAM_TOKEN not set in .env")

    logger.info('Starting Tour Bot with polling...')

    # Build application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    from telegram.ext import MessageHandler, CallbackQueryHandler, filters

    # Handle all messages
    async def message_handler(update: Update, context):
        await handle_message(update, application)

    # Handle callback queries
    async def callback_handler(update: Update, context):
        await handle_callback(update, application)

    application.add_handler(MessageHandler(filters.ALL, message_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))

    # Start polling
    logger.info('Bot polling started. Listening for messages...')
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    asyncio.run(main())
