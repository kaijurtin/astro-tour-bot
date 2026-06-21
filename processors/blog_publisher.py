import os
import logging
from datetime import datetime
import json
import shutil

logger = logging.getLogger(__name__)

# NAS drop folder — Mac picks these up and deploys
NAS_OUTBOX = os.getenv('NAS_OUTBOX', '/mnt/nas/tour-inputs/outbox')
ASTRO_REPO = os.getenv('ASTRO_REPO', '/opt/astro')


async def publish_blog_entry(job_id: str, job: dict) -> str:
    """
    Write blog entry files to the NAS outbox.
    Returns the markdown filename so the caller can report it.

    Deploy flow (runs on Mac, not CT 115):
      1. rsync /mnt/nas/tour-inputs/outbox/ → /Users/kaijurtin/repos/jurtin-astro/
      2. npm run build
      3. bash /tmp/sftp_upload.sh
    """
    logger.info(f'[{job_id}] Writing blog entry to outbox...')

    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H%M%S')
    filename = f'tour-{date_str}-{time_str}.md'

    # Parse route_stats — may arrive as JSON string or dict
    route_stats = job.get('route_stats') or {}
    if isinstance(route_stats, str):
        try:
            route_stats = json.loads(route_stats)
        except Exception:
            route_stats = {}

    # Build photo public URLs after copying
    photos_src = [p for p in (job.get('photos') or '').split(',') if p]
    photo_urls = _copy_photos(photos_src, job_id, now)
    hero_image = photo_urls[0] if photo_urls else ''

    transcript = job.get('transcription', '').strip()
    title = job.get('title', f'Tour Entry {date_str}')

    markdown = _build_markdown(
        title=title,
        date_str=date_str,
        transcript=transcript,
        route_stats=route_stats,
        photo_urls=photo_urls,
        hero_image=hero_image,
        edit_window_expires=job.get('edit_window_expires', ''),
    )

    # Write markdown to outbox
    blog_outbox = os.path.join(NAS_OUTBOX, 'src', 'content', 'blog')
    os.makedirs(blog_outbox, exist_ok=True)
    filepath = os.path.join(blog_outbox, filename)
    with open(filepath, 'w') as f:
        f.write(markdown)

    logger.info(f'[{job_id}] Written: {filepath}')
    return filename


def _copy_photos(src_paths: list, job_id: str, timestamp: datetime) -> list:
    """Copy photos to NAS outbox public dir, return their web URLs."""
    year = timestamp.strftime('%Y')
    month = timestamp.strftime('%m')
    day = timestamp.strftime('%d')

    dest_dir = os.path.join(NAS_OUTBOX, 'public', 'images', 'tour', year, month, day)
    os.makedirs(dest_dir, exist_ok=True)

    urls = []
    for i, src in enumerate(src_paths):
        if os.path.exists(src):
            dest = os.path.join(dest_dir, f'photo_{i+1}.jpg')
            shutil.copy2(src, dest)
            urls.append(f'/images/tour/{year}/{month}/{day}/photo_{i+1}.jpg')
            logger.info(f'[{job_id}] Photo copied → {dest}')
    return urls


def _build_markdown(*, title, date_str, transcript, route_stats,
                    photo_urls, hero_image, edit_window_expires) -> str:
    photos_yaml = '\n'.join(f'  - "{p}"' for p in photo_urls)
    return f"""---
title: "{title}"
date: {date_str}
category: testentry
heroImage: "{hero_image}"
excerpt: "{transcript[:120].replace('"', "'")}"
images:
{photos_yaml if photos_yaml else '  []'}
distance: {route_stats.get('distance_km', 0)}
elevation_gain: {route_stats.get('elevation_gain_m', 0)}
elevation_loss: {route_stats.get('elevation_loss_m', 0)}
avg_speed: {route_stats.get('avg_speed_kmh', '')}
---

{transcript}
"""
