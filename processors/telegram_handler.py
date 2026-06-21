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

    # ── Commands ──────────────────────────────────────────────────────────────

    if message.text == '/new' or message.text == '/new_entry':
        if _has_active_entry(context):
            await context.bot.send_message(
                chat_id=chat_id,
                text='⚠️ An entry is already open.\n\nSend /publish to publish it or /cancel to discard it.'
            )
            return

        context.user_data['current_job'] = {
            'user_id': user_id,
            'chat_id': chat_id,
            'texts': [],
            'audios': [],
            'photos': [],
            'gpx': None,
            'started_at': datetime.now().isoformat()
        }
        await context.bot.send_message(
            chat_id=chat_id,
            text='📖 New entry started!\n\nSend any combination of:\n📝 Text messages\n🎙️ Voice messages\n📸 Photos\n🗺️ GPX file\n\nType /publish when done or /status to see what\'s collected.'
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

    if message.text in ('/start', '/help'):
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                '🚴 *Tour Blog Bot*\n\n'
                '*Commands:*\n'
                '/new — start a new blog entry\n'
                '/status — see what\'s collected so far\n'
                '/publish — publish the current entry\n'
                '/cancel — discard the current entry\n\n'
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
            'edit_window_expires': entry_data['edit_window_expires'],
            'photos': ','.join(job_data.get('photos', [])),
            'gpx_file': job_data.get('gpx'),
            'location': job_data.get('location', '')
        }

        update_job(
            job_id,
            transcription=entry_data['transcript'],
            title=entry_data['title'],
            route_stats=entry_data.get('route_stats'),
            status='auto-published',
            auto_published_at=entry_data['auto_published_at'],
            edit_window_expires=entry_data['edit_window_expires']
        )

        await publish_blog_entry(job_id, job_record)

        n_photos = len(job_data.get('photos', []))
        n_audios = len(job_data.get('audios', []))
        n_texts = len(job_data.get('texts', []))

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f'✅ *Published!*\n\n'
                f'*{entry_data["title"]}*\n\n'
                f'📝 {n_texts} text note(s) · 🎙️ {n_audios} audio(s) · 📸 {n_photos} photo(s)\n\n'
                f'🔗 https://jurtin.de/blog/\n\n'
                f'📝 Edit window: *30 minutes remaining*'
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
