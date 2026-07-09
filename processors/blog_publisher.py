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
STAGING_HOST = os.getenv('STAGING_HOST', '192.168.178.216')
STAGING_SSH_KEY = os.getenv('STAGING_SSH_KEY', '/root/.ssh/staging_deploy')
STAGING_REMOTE_DIR = os.getenv('STAGING_REMOTE_DIR', '/var/www/staging')


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
    5. rsync dist/ to the staging site (staging.jurtin.de on CT111)
    Production (jurtin.de) is only updated by the separate /golive command.
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

    # Copy GPX track to Astro public dir (if one was attached)
    gpx_url = _copy_gpx(route_stats.get('gpx_path'), job_id, now)

    transcript = (job.get('transcription') or '').strip()
    title = job.get('title') or f'Tour Entry {date_str}'

    # Write markdown
    os.makedirs(BLOG_DIR, exist_ok=True)
    filepath = os.path.join(BLOG_DIR, filename)
    with open(filepath, 'w') as f:
        f.write(_build_markdown(
            title=title,
            date_str=date_str,
            category=job.get('category', 'testentry'),
            transcript=transcript,
            route_stats=route_stats,
            photo_urls=photo_urls,
            hero_image=hero_image,
            gpx_url=gpx_url,
        ))
    logger.info(f'[{job_id}] Markdown written: {filepath}')

    # Git commit + push (best-effort — don't fail the whole pipeline)
    try:
        _git_commit_push(filename, job_id, gpx_url)
    except Exception as e:
        logger.warning(f'[{job_id}] Git push skipped: {e}')

    # Build
    logger.info(f'[{job_id}] Building Astro site...')
    _npm(['run', 'build'], cwd=ASTRO_REPO)
    logger.info(f'[{job_id}] Build complete')

    # Deploy to staging (production is a separate, manual /golive step)
    logger.info(f'[{job_id}] Deploying to staging...')
    _deploy_staging()
    logger.info(f'[{job_id}] Staging deploy complete')

    return filename


def _deploy_staging():
    """Push the current dist/ build to the staging site (staging.jurtin.de)."""
    subprocess.run([
        'rsync', '-az', '--delete',
        '-e', f'ssh -i {STAGING_SSH_KEY} -o StrictHostKeyChecking=no',
        os.path.join(ASTRO_REPO, 'dist') + '/',
        f'root@{STAGING_HOST}:{STAGING_REMOTE_DIR}/',
    ], check=True, timeout=300)


def deploy_to_production():
    """Promote the current dist/ build (already reviewed on staging) to jurtin.de."""
    subprocess.run(['bash', DEPLOY_SCRIPT], check=True, timeout=600)


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


def _copy_gpx(gpx_src_path: str | None, job_id: str, timestamp: datetime) -> str | None:
    if not gpx_src_path or not os.path.exists(gpx_src_path):
        return None
    year, month, day = timestamp.strftime('%Y'), timestamp.strftime('%m'), timestamp.strftime('%d')
    dest_dir = os.path.join(ASTRO_REPO, 'public', 'tracks', year, month, day)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, 'route.gpx')
    shutil.copy2(gpx_src_path, dest)
    logger.info(f'[{job_id}] GPX → {dest}')
    return f'/tracks/{year}/{month}/{day}/route.gpx'


def _git_commit_push(filename: str, job_id: str, gpx_url: str | None):
    env = os.environ.copy()
    env['GIT_SSH_COMMAND'] = 'ssh -i /root/.ssh/github_deploy -o StrictHostKeyChecking=no'
    add_paths = [f'src/content/blog/{filename}', 'public/images/tour/']
    if gpx_url:
        add_paths.append('public/tracks/')
    subprocess.run(['git', 'add', *add_paths],
                   cwd=ASTRO_REPO, check=True, env=env)
    subprocess.run(['git', 'commit', '-m', f'feat: add tour entry {filename}'],
                   cwd=ASTRO_REPO, check=True, env=env)
    subprocess.run(['git', 'push', 'origin', 'main'],
                   cwd=ASTRO_REPO, check=True, env=env)
    logger.info(f'[{job_id}] Git pushed')


def _build_markdown(*, title, date_str, category, transcript, route_stats,
                    photo_urls, hero_image, gpx_url=None) -> str:
    photos_yaml = '\n'.join(f'  - "{p}"' for p in photo_urls) or '  []'
    excerpt = transcript[:120].replace('"', "'")

    # Omit any stat that's None rather than interpolating the literal string "None" (invalid YAML)
    stats_fields = [
        ('distance', route_stats.get('distance_km', 0)),
        ('elevation_gain', route_stats.get('elevation_gain_m', 0)),
        ('elevation_loss', route_stats.get('elevation_loss_m', 0)),
        ('avg_speed', route_stats.get('avg_speed_kmh')),
    ]
    stats_yaml = ''.join(f'{key}: {value}\n' for key, value in stats_fields if value is not None)
    gpx_yaml = f'gpx: "{gpx_url}"\n' if gpx_url else ''

    return f"""---
title: "{title}"
date: {date_str}
category: {category}
heroImage: "{hero_image}"
excerpt: "{excerpt}"
images:
{photos_yaml}
{stats_yaml}{gpx_yaml}---

{transcript}
"""
