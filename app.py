import os
import json
import sqlite3
import hashlib
from datetime import datetime
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes
import logging

from processors.telegram_handler import handle_message, handle_callback
from processors.blog_processor import process_tour_input
from database import init_db, get_db

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Config
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://jurtin.de/tour-bot/webhook')
UPLOADS_DIR = os.getenv('UPLOADS_DIR', '/mnt/nas/tour-inputs')
ASTRO_REPO = os.getenv('ASTRO_REPO', '/opt/astro')

# Ensure directories exist
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(f'{UPLOADS_DIR}/pending', exist_ok=True)
os.makedirs(f'{UPLOADS_DIR}/processed', exist_ok=True)

# Initialize database
init_db()

# Initialize Telegram bot
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()


@app.route('/tour-bot/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram updates"""
    try:
        update_data = request.get_json()
        update = Update.de_json(update_data, telegram_app.bot)

        # Handle message or callback query
        if update.message:
            handle_message(update, telegram_app)
        elif update.callback_query:
            handle_callback(update, telegram_app)

        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f'Webhook error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/tour-bot/status', methods=['GET'])
def status():
    """Health check"""
    return jsonify({
        'status': 'running',
        'bot': 'KaiKiste_bot',
        'timestamp': datetime.now().isoformat()
    })


@app.route('/tour-bot/jobs', methods=['GET'])
def list_jobs():
    """List pending/processed jobs"""
    db = get_db()
    cursor = db.cursor()

    pending = cursor.execute(
        'SELECT id, created_at, status FROM jobs WHERE status = ? ORDER BY created_at DESC',
        ('pending',)
    ).fetchall()

    processed = cursor.execute(
        'SELECT id, created_at, status FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT 10',
        ('published',)
    ).fetchall()

    return jsonify({
        'pending': [dict(row) for row in pending],
        'recent': [dict(row) for row in processed]
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
