import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from database import create_job, update_job, get_job
from processors.blog_processor import process_tour_input
from telegram.ext import ContextTypes

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

    # Handle /done command to finalize
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

I'll rewrite your notes into a beautiful blog entry using AI.

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
            text='Send voice message, photos, or GPX file. Type /help for instructions.'
        )


async def finalize_job(context: ContextTypes.DEFAULT_TYPE, job_data):
    """Create job and start processing"""
    try:
        job_id = create_job(
            user_id=job_data['user_id'],
            voice_file=job_data['voice'],
            photos=job_data['photos'],
            gpx_file=job_data['gpx']
        )

        chat_id = job_data['chat_id']

        await context.bot.send_message(
            chat_id=chat_id,
            text='⏳ Processing your blog entry...'
        )

        # Process the job (transcription + rewriting)
        blog_content, blog_title = await process_tour_input(job_id, job_data)

        # Store in database
        update_job(job_id, transcription=blog_content, status='preview')

        # Send preview with approval buttons
        preview_text = f'''
**Blog Preview:**

**{blog_title}**

{blog_content[:500]}...

Ready to publish?
        '''

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton('✅ Approve & Publish', callback_data=f'approve_{job_id}'),
                InlineKeyboardButton('❌ Edit/Reject', callback_data=f'reject_{job_id}')
            ]
        ])

        await context.bot.send_message(
            chat_id=chat_id,
            text=preview_text,
            parse_mode='Markdown',
            reply_markup=keyboard
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
    """Handle approval/rejection callbacks"""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if query.data.startswith('approve_'):
        job_id = query.data.replace('approve_', '')
        await approve_and_publish(context, job_id, chat_id)
        await query.edit_message_text(text='✅ Blog published!')

    elif query.data.startswith('reject_'):
        job_id = query.data.replace('reject_', '')
        await context.bot.send_message(
            chat_id=chat_id,
            text='Noted. Please send your next day\'s content to retry. /help for instructions.'
        )
        await query.edit_message_text(text='❌ Rejected')


async def approve_and_publish(context: ContextTypes.DEFAULT_TYPE, job_id: str, chat_id: int):
    """Publish blog entry"""
    from processors.blog_publisher import publish_blog_entry

    try:
        job = get_job(job_id)
        # Publish to Astro blog
        await publish_blog_entry(job_id, job)
        update_job(job_id, status='published')

        await context.bot.send_message(
            chat_id=chat_id,
            text='🎉 Your blog entry has been published!\n\nhttps://jurtin.de/blog/'
        )
    except Exception as e:
        logger.error(f'Publishing error: {e}')
        await context.bot.send_message(
            chat_id=chat_id,
            text=f'❌ Publishing error: {e}'
        )
