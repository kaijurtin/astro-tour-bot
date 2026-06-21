import os
import logging
import subprocess
from datetime import datetime
import json
import shutil

logger = logging.getLogger(__name__)

ASTRO_REPO = os.getenv('ASTRO_REPO', '/opt/astro')
BLOG_DIR = os.path.join(ASTRO_REPO, 'src', 'content', 'blog')
DEPLOY_SCRIPT = os.getenv('DEPLOY_SCRIPT', '/opt/sftp_upload.sh')
NVM_NODE = '/root/.nvm/versions/node/v22.23.0/bin'


def _npm(args: list, cwd: str):
    """Run npm with nvm Node 22 in PATH."""
    env = os.environ.copy()
    env['PATH'] = f"{NVM_NODE}:{env.get('PATH', '')}"
    subprocess.run(['npm'] + args, cwd=cwd, check=True, env=env)


async def publish_blog_entry(job_id: str, job: dict) -> str:
    """
    Full pipeline on CT 115:
    1. Write markdown to /opt/astro/src/content/blog/
    2. Copy photos to /opt/astro/public/images/tour/
    3. git add + commit + push (keeps GitHub in sync)
    4. npm run build
    5. sftp upload to IONOS
    """
    logger.info(f'[{job_id}] Publishing blog entry...')

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

    # Copy photos to Astro public dir
    photos_src = [p for p in (job.get('photos') or '').split(',') if p]
    photo_urls = _copy_photos(photos_src, job_id, now)
    hero_image = photo_urls[0] if photo_urls else ''

    transcript = (job.get('transcription') or '').strip()
    title = job.get('title') or f'Tour Entry {date_str}'

    # Write markdown
    os.makedirs(BLOG_DIR, exist_ok=True)
    filepath = os.path.join(BLOG_DIR, filename)
    with open(filepath, 'w') as f:
        f.write(_build_markdown(
            title=title,
            date_str=date_str,
            transcript=transcript,
            route_stats=route_stats,
            photo_urls=photo_urls,
            hero_image=hero_image,
            edit_window_expires=job.get('edit_window_expires', ''),
        ))
    logger.info(f'[{job_id}] Markdown written: {filepath}')

    # Git commit + push (best-effort — don't fail the whole pipeline)
    try:
        _git_commit_push(filename, job_id)
    except Exception as e:
        logger.warning(f'[{job_id}] Git push skipped: {e}')

    # Build
    logger.info(f'[{job_id}] Building Astro site...')
    _npm(['run', 'build'], cwd=ASTRO_REPO)
    logger.info(f'[{job_id}] Build complete')

    # Deploy
    logger.info(f'[{job_id}] Deploying to IONOS...')
    subprocess.run(['bash', DEPLOY_SCRIPT], check=True, timeout=600)
    logger.info(f'[{job_id}] Deploy complete')

    return filename


def _copy_photos(src_paths: list, job_id: str, timestamp: datetime) -> list:
    year, month, day = timestamp.strftime('%Y'), timestamp.strftime('%m'), timestamp.strftime('%d')
    dest_dir = os.path.join(ASTRO_REPO, 'public', 'images', 'tour', year, month, day)
    os.makedirs(dest_dir, exist_ok=True)
    urls = []
    for i, src in enumerate(src_paths):
        if os.path.exists(src):
            dest = os.path.join(dest_dir, f'photo_{i+1}.jpg')
            shutil.copy2(src, dest)
            urls.append(f'/images/tour/{year}/{month}/{day}/photo_{i+1}.jpg')
            logger.info(f'[{job_id}] Photo → {dest}')
    return urls


def _git_commit_push(filename: str, job_id: str):
    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = 'ssh -i /root/.ssh/github_deploy -o StrictHostKeyChecking=no'
    subprocess.run(['git', 'add', f'src/content/blog/{filename}', 'public/images/tour/'],
                   cwd=ASTRO_REPO, check=True, env=env)
    subprocess.run(['git', 'commit', '-m', f'feat: add tour entry {filename}'],
                   cwd=ASTRO_REPO, check=True, env=env)
    subprocess.run(['git', 'push', 'origin', 'main'],
                   cwd=ASTRO_REPO, check=True, env=env)
    logger.info(f'[{job_id}] Git pushed')


def _build_markdown(*, title, date_str, transcript, route_stats,
                    photo_urls, hero_image, edit_window_expires) -> str:
    photos_yaml = '\n'.join(f'  - "{p}"' for p in photo_urls) or '  []'
    excerpt = transcript[:120].replace('"', "'")
    return f"""---
title: "{title}"
date: {date_str}
category: testentry
heroImage: "{hero_image}"
excerpt: "{excerpt}"
images:
{photos_yaml}
distance: {route_stats.get('distance_km', 0)}
elevation_gain: {route_stats.get('elevation_gain_m', 0)}
elevation_loss: {route_stats.get('elevation_loss_m', 0)}
avg_speed: {route_stats.get('avg_speed_kmh', '')}
---

{transcript}
"""
