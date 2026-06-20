import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from database import create_job, update_job, get_job
from processors.blog_processor import process_tour_input

logger = logging.getLogger(__name__)

UPLOADS_DIR = os.getenv('UPLOADS_DIR', '/mnt/nas/tour-inputs')
PENDING_DIR = f'{UPLOADS_DIR}/pending'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming Telegram messages"""
    message = update.message
    user_id = message.from_user.id
    chat_id = message.chat_id

    # Initialize user data if needed
    if 'current_job' not in context.user_data:
        context.user_data['current_job'] = {
            'user_id': user_id,
            'chat_id': chat_id,
            'voice': None,
            'photos': [],
            'gpx': None,
            'transcription': None,
            'started_at': datetime.now()
        }

    current_job = context.user_data['current_job']

    # Handle text message (description of the day)
    if message.text and not message.text.startswith('/'):
        current_job['transcription'] = message.text
        await context.bot.send_message(
            chat_id=chat_id,
            text='✅ Day notes received! Send photos and GPX next.'
        )

    # Handle photos
    elif message.photo:
        try:
            photo_file = await context.bot.get_file(message.photo[-1].file_id)
            photo_path = f'{PENDING_DIR}/photo_{user_id}_{datetime.now().timestamp()}.jpg'
            await photo_file.download_to_drive(photo_path)
            current_job['photos'].append(photo_path)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'📸 Photo {len(current_job["photos"])} received!'
            )
        except Exception as e:
            logger.error(f'Photo download error: {e}')
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'❌ Error downloading photo: {e}'
            )

    # Handle document (GPX file)
    elif message.document:
        if message.document.file_name.endswith('.gpx'):
            try:
                doc_file = await context.bot.get_file(message.document.file_id)
                gpx_path = f'{PENDING_DIR}/route_{user_id}_{datetime.now().timestamp()}.gpx'
                await doc_file.download_to_drive(gpx_path)
                current_job['gpx'] = gpx_path
                await context.bot.send_message(
                    chat_id=chat_id,
                    text='🗺️ Route (GPX) received!'
                )
            except Exception as e:
                logger.error(f'GPX download error: {e}')
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f'❌ Error downloading GPX: {e}'
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text='ℹ️ Please send GPX files only for routes.'
            )

    # Handle /done command to finalize and auto-publish
    elif message.text == '/done':
        if current_job.get('transcription') and current_job['photos'] and current_job['gpx']:
            await finalize_job(context, current_job)
        else:
            missing = []
            if not current_job.get('transcription'):
                missing.append('day notes (text)')
            if not current_job['photos']:
                missing.append('photos')
            if not current_job['gpx']:
                missing.append('route (GPX)')
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'⚠️ Missing: {", ".join(missing)}\n\nSend: text message → photos → GPX → /done'
            )

    # Help command
    elif message.text == '/start' or message.text == '/help':
        help_text = '''🚴 **Bicycle Tour Blog Bot**

**Daily entry process:**

1. 📝 Send a text message with your day's notes
2. 📸 Send your photos
3. 🗺️ Send your GPX route file
4. Type `/done` to submit!

Your entry will be published immediately with a 30-minute edit window.

**Example:**
"Started early, beautiful weather, 45km to La Roche, great campground with river"
        '''
        await context.bot.send_message(
            chat_id=chat_id,
            text=help_text,
            parse_mode='Markdown'
        )

    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text='Send your day notes (text), photos, and GPX file. Type /help for instructions.'
        )


async def finalize_job(context: ContextTypes.DEFAULT_TYPE, job_data):
    """Process and immediately auto-publish blog entry with edit window"""
    try:
        job_id = create_job(
            user_id=job_data['user_id'],
            photos=job_data['photos'],
            gpx_file=job_data['gpx']
        )

        chat_id = job_data['chat_id']

        await context.bot.send_message(
            chat_id=chat_id,
            text='⏳ Processing and publishing...'
        )

        # Process the raw entry (no Ollama rewriting, just transcription + GPX stats)
        entry_data = await process_tour_input(job_id, job_data)

        # Store in database
        update_job(
            job_id,
            transcription=entry_data['transcript'],
            title=entry_data['title'],
            route_stats=entry_data.get('route_stats'),
            status='auto-published',
            auto_published_at=entry_data['auto_published_at'],
            edit_window_expires=entry_data['edit_window_expires']
        )

        # Generate entry URL
        entry_slug = f"day-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        entry_url = f"https://jurtin.de/blog/tour/{entry_slug}"

        # Send auto-publish confirmation with edit window info
        publish_message = f'''✅ **Published!**

**{entry_data['title']}**

🔗 {entry_url}

📝 Edit window: **30 minutes remaining**
You can still edit the entry for the next 30 minutes.

When the edit window closes, the entry will be finalized.
        '''

        await context.bot.send_message(
            chat_id=chat_id,
            text=publish_message,
            parse_mode='Markdown'
        )

        # Clear current job
        context.user_data['current_job'] = None

    except Exception as e:
        logger.error(f'Job finalization error: {e}')
        await context.bot.send_message(
            chat_id=job_data['chat_id'],
            text=f'❌ Error processing: {e}'
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any callback queries (edit window actions, etc.)"""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    # Future: add edit/close window callbacks here if needed
    pass
