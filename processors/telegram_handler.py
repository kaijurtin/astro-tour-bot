import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes
from database import create_job, update_job, get_job
from processors.blog_processor import process_tour_input

# app.py also calls load_dotenv(), but only AFTER importing this module — so
# ALLOWED_USER_IDS below would otherwise always read as unset. Load here too
# (idempotent) so this module's env reads are correct regardless of import order.
load_dotenv()

logger = logging.getLogger(__name__)

UPLOADS_DIR = os.getenv('UPLOADS_DIR', '/mnt/nas/tour-inputs')
PENDING_DIR = f'{UPLOADS_DIR}/pending'

ALLOWED_USER_IDS = {
    int(uid.strip()) for uid in os.getenv('ALLOWED_USER_IDS', '').split(',') if uid.strip()
}


def _has_active_entry(context) -> bool:
    return context.user_data.get('current_job') is not None


def _entry_summary(job: dict) -> str:
    """Build a short status string of what's collected so far."""
    parts = []
    texts = job.get('texts', [])
    audios = job.get('audios', [])
    photos = job.get('photos', [])
    gpx = job.get('gpx')
    if texts:
        parts.append(f'📝 {len(texts)} text message(s)')
    if audios:
        parts.append(f'🎙️ {len(audios)} audio message(s)')
    if photos:
        parts.append(f'📸 {len(photos)} photo(s)')
    if gpx:
        parts.append('🗺️ GPX route')
    return '\n'.join(parts) if parts else '(nothing yet)'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all incoming messages based on entry state."""
    message = update.message
    user_id = message.from_user.id
    chat_id = message.chat_id

    if ALLOWED_USER_IDS:
        if user_id not in ALLOWED_USER_IDS:
            logger.warning(f'Unauthorized access attempt from user_id={user_id} chat_id={chat_id}')
            await context.bot.send_message(
                chat_id=chat_id,
                text='🚫 This bot is private. You are not authorized to use it.'
            )
            return
    else:
        logger.info(
            f'ALLOWED_USER_IDS not configured — message from user_id={user_id}. '
            f'Add this ID to ALLOWED_USER_IDS in .env to restrict bot access.'
        )

    # ── Commands ──────────────────────────────────────────────────────────────

    if message.text == '/new' or message.text == '/new_entry':
        if _has_active_entry(context):
            await context.bot.send_message(
                chat_id=chat_id,
                text='⚠️ An entry is already open.\n\nSend /publish to publish it or /cancel to discard it.'
            )
            return

        default_cat = context.user_data.get('default_category', 'testentry')
        context.user_data['current_job'] = {
            'user_id': user_id,
            'chat_id': chat_id,
            'texts': [],
            'audios': [],
            'photos': [],
            'gpx': None,
            'category': default_cat,
            'started_at': datetime.now().isoformat()
        }
        await context.bot.send_message(
            chat_id=chat_id,
            text=f'📖 New entry started! Category: *{default_cat}*\n\nSend any combination of:\n📝 Text messages\n🎙️ Voice messages\n📸 Photos\n🗺️ GPX file\n\nChange category: /category <name>\nPublish: /publish',
            parse_mode='Markdown'
        )
        return

    if message.text == '/publish' or message.text == '/stop' or message.text == '/done':
        if not _has_active_entry(context):
            await context.bot.send_message(
                chat_id=chat_id,
                text='ℹ️ No active entry. Start one with /new'
            )
            return
        job = context.user_data['current_job']
        if not job['texts'] and not job['audios']:
            await context.bot.send_message(
                chat_id=chat_id,
                text='⚠️ Entry has no text or audio yet. Add some notes before publishing.'
            )
            return
        await finalize_job(context, job)
        return

    if message.text == '/status':
        if not _has_active_entry(context):
            await context.bot.send_message(
                chat_id=chat_id,
                text='ℹ️ No active entry. Start one with /new'
            )
            return
        job = context.user_data['current_job']
        await context.bot.send_message(
            chat_id=chat_id,
            text=f'📋 Current entry:\n\n{_entry_summary(job)}\n\nType /publish when ready or /cancel to discard.'
        )
        return

    if message.text == '/cancel':
        if not _has_active_entry(context):
            await context.bot.send_message(chat_id=chat_id, text='ℹ️ No active entry to cancel.')
            return
        context.user_data['current_job'] = None
        await context.bot.send_message(chat_id=chat_id, text='🗑️ Entry discarded. Start a new one with /new')
        return

    if message.text and message.text.startswith('/category'):
        parts = message.text.split(None, 1)
        if len(parts) < 2 or not parts[1].strip():
            current = (context.user_data.get('current_job') or {}).get('category', 'testentry')
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'📁 Current category: *{current}*\n\nTo change: /category <name>\nExample: /category belgientour',
                parse_mode='Markdown'
            )
            return
        # Normalise: lowercase, spaces → hyphens
        new_cat = parts[1].strip().lower().replace(' ', '-')
        if _has_active_entry(context):
            context.user_data['current_job']['category'] = new_cat
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'📁 Category set to *{new_cat}* for this entry.',
                parse_mode='Markdown'
            )
        else:
            # Set as default for the next /new
            context.user_data['default_category'] = new_cat
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'📁 Default category set to *{new_cat}*. Will apply to the next /new entry.',
                parse_mode='Markdown'
            )
        return

    if message.text == '/golive':
        await context.bot.send_message(chat_id=chat_id, text='🚀 Promoting staging to production...')
        try:
            from processors.blog_publisher import deploy_to_production
            deploy_to_production()
            await context.bot.send_message(
                chat_id=chat_id,
                text='✅ Live! https://jurtin.de/blog/'
            )
        except Exception as e:
            logger.error(f'Go-live error: {e}')
            await context.bot.send_message(chat_id=chat_id, text=f'❌ Go-live failed: {e}')
        return

    if message.text in ('/start', '/help'):
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                '🚴 *Tour Blog Bot*\n\n'
                '*Commands:*\n'
                '/new — start a new blog entry\n'
                '/status — see what\'s collected so far\n'
                '/publish — publish the current entry (to staging)\n'
                '/cancel — discard the current entry\n'
                '/golive — promote the current staging build to jurtin.de\n\n'
                '*While an entry is open, send any of:*\n'
                '📝 Text messages (your notes)\n'
                '🎙️ Voice messages\n'
                '📸 Photos\n'
                '🗺️ GPX file (attach as document)\n\n'
                'Multiple messages of each type are allowed.'
            ),
            parse_mode='Markdown'
        )
        return

    # ── Content messages (only accepted when an entry is open) ────────────────

    if not _has_active_entry(context):
        await context.bot.send_message(
            chat_id=chat_id,
            text='ℹ️ No active entry. Start one first with /new'
        )
        return

    job = context.user_data['current_job']

    # Text note
    if message.text and not message.text.startswith('/'):
        job['texts'].append(message.text)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f'📝 Text note #{len(job["texts"])} added.'
        )

    # Voice / audio message
    elif message.voice or message.audio:
        try:
            audio_obj = message.voice or message.audio
            audio_file = await context.bot.get_file(audio_obj.file_id)
            ext = 'ogg' if message.voice else 'mp3'
            audio_path = f'{PENDING_DIR}/audio_{user_id}_{datetime.now().timestamp()}.{ext}'
            await audio_file.download_to_drive(audio_path)
            job['audios'].append(audio_path)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'🎙️ Audio #{len(job["audios"])} received.'
            )
        except Exception as e:
            logger.error(f'Audio download error: {e}')
            await context.bot.send_message(chat_id=chat_id, text=f'❌ Error saving audio: {e}')

    # Photo
    elif message.photo:
        try:
            photo_file = await context.bot.get_file(message.photo[-1].file_id)
            photo_path = f'{PENDING_DIR}/photo_{user_id}_{datetime.now().timestamp()}.jpg'
            await photo_file.download_to_drive(photo_path)
            job['photos'].append(photo_path)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'📸 Photo #{len(job["photos"])} added.'
            )
        except Exception as e:
            logger.error(f'Photo download error: {e}')
            await context.bot.send_message(chat_id=chat_id, text=f'❌ Error saving photo: {e}')

    # Document (GPX or other)
    elif message.document:
        if message.document.file_name.lower().endswith('.gpx'):
            try:
                doc_file = await context.bot.get_file(message.document.file_id)
                gpx_path = f'{PENDING_DIR}/route_{user_id}_{datetime.now().timestamp()}.gpx'
                await doc_file.download_to_drive(gpx_path)
                job['gpx'] = gpx_path
                await context.bot.send_message(chat_id=chat_id, text='🗺️ GPX route received.')
            except Exception as e:
                logger.error(f'GPX download error: {e}')
                await context.bot.send_message(chat_id=chat_id, text=f'❌ Error saving GPX: {e}')
        else:
            await context.bot.send_message(chat_id=chat_id, text='ℹ️ Only GPX files are supported for routes.')

    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text='ℹ️ Unsupported message type. Send text, voice, photos, or a GPX file.'
        )


async def finalize_job(context: ContextTypes.DEFAULT_TYPE, job_data: dict):
    """Process and auto-publish the current entry."""
    from processors.blog_publisher import publish_blog_entry

    chat_id = job_data['chat_id']

    try:
        # Combine all text notes into one transcription
        all_text = '\n\n'.join(job_data.get('texts', []))
        job_data['transcription'] = all_text

        job_id = create_job(
            user_id=job_data['user_id'],
            photos=job_data.get('photos', []),
            gpx_file=job_data.get('gpx')
        )

        await context.bot.send_message(chat_id=chat_id, text='⏳ Processing and publishing...')

        entry_data = await process_tour_input(job_id, job_data)

        job_record = {
            'id': job_id,
            'transcription': entry_data['transcript'],
            'title': entry_data['title'],
            'route_stats': entry_data.get('route_stats'),
            'status': 'auto-published',
            'auto_published_at': entry_data['auto_published_at'],
            'photos': ','.join(job_data.get('photos', [])),
            'gpx_file': job_data.get('gpx'),
            'location': job_data.get('location', '')
        }

        import json as _json
        update_job(
            job_id,
            transcription=entry_data['transcript'],
            title=entry_data['title'],
            route_stats=_json.dumps(entry_data.get('route_stats')) if entry_data.get('route_stats') else None,
            status='auto-published',
            auto_published_at=entry_data['auto_published_at']
        )

        await publish_blog_entry(job_id, job_record)

        n_photos = len(job_data.get('photos', []))
        n_audios = len(job_data.get('audios', []))
        n_texts = len(job_data.get('texts', []))

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f'✅ *Published to staging!*\n\n'
                f'*{entry_data["title"]}*\n\n'
                f'📝 {n_texts} text note(s) · 🎙️ {n_audios} audio(s) · 📸 {n_photos} photo(s)\n\n'
                f'🔗 https://staging.jurtin.de/blog/\n\n'
                f'Ready to go live? Send /golive'
            ),
            parse_mode='Markdown'
        )

        context.user_data['current_job'] = None

    except Exception as e:
        logger.error(f'Job finalization error: {e}')
        await context.bot.send_message(chat_id=chat_id, text=f'❌ Error processing: {e}')


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries."""
    query = update.callback_query
    await query.answer()
