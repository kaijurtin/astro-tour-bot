import os
import logging
import subprocess
from datetime import datetime
import json
from pathlib import Path
import shutil

logger = logging.getLogger(__name__)

ASTRO_REPO = os.getenv('ASTRO_REPO', '/opt/astro')
BLOG_DIR = f'{ASTRO_REPO}/src/content/blog'


async def publish_blog_entry(job_id: str, job: dict):
    """
    Publish blog entry to Astro site:
    1. Create markdown file with raw telegraphic format
    2. Copy photos to public directory
    3. Commit to git
    4. Trigger build and deploy
    """
    try:
        logger.info(f'[{job_id}] Publishing blog entry...')

        # Generate filename (tour-etappe-YYYY-MM-DD-HHmmss)
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H%M%S')
        filename = f'tour-{date_str}-{time_str}.md'
        filepath = f'{BLOG_DIR}/{filename}'

        # Parse route stats
        route_stats = job.get('route_stats', {})
        photos_list = job.get('photos', '').split(',') if job.get('photos') else []
        hero_image = photos_list[0] if photos_list else '/images/blog/default.jpg'

        # Build photo references for markdown
        photo_refs = []
        if photos_list:
            for i, photo in enumerate(photos_list):
                # Convert path to URL
                photo_url = photo.replace(ASTRO_REPO, '').replace('/public', '')
                photo_refs.append(photo_url)

        # Create frontmatter for new telegraphic blog format
        frontmatter = {
            'title': job.get('title', f'Tour Entry {date_str}'),
            'date': date_str,
            'category': 'biketour',
            'layout': 'DailyEntryLayout',
            'transcript': job.get('transcription', ''),
            'location': job.get('location', ''),
            'distance': route_stats.get('distance_km', 0),
            'elevation_gain': route_stats.get('elevation_gain_m', 0),
            'elevation_loss': route_stats.get('elevation_loss_m', 0),
            'avg_speed': route_stats.get('avg_speed_kmh'),
            'photos': photo_refs,
            'heroImage': hero_image,
            'isAutoPublished': True,
            'editWindowExpires': job.get('edit_window_expires'),
        }

        # Create markdown content with raw transcript
        markdown_content = f"""---
title: "{frontmatter['title']}"
date: {frontmatter['date']}
category: {frontmatter['category']}
layout: {frontmatter['layout']}
transcript: |
  {json.dumps(frontmatter['transcript'])}
location: "{frontmatter['location']}"
distance: {frontmatter['distance']}
elevation_gain: {frontmatter['elevation_gain']}
elevation_loss: {frontmatter['elevation_loss']}
avg_speed: {frontmatter['avg_speed']}
heroImage: "{frontmatter['heroImage']}"
photos:
{chr(10).join(f'  - "{photo}"' for photo in frontmatter['photos'])}
isAutoPublished: true
editWindowExpires: "{frontmatter['editWindowExpires']}"
---

{frontmatter['transcript']}
"""

        # Write markdown file
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w') as f:
            f.write(markdown_content)

        logger.info(f'[{job_id}] Blog file created: {filepath}')

        # Copy photos to public directory
        if photos_list:
            logger.info(f'[{job_id}] Copying photos...')
            copy_photos_to_public(photos_list, job_id, now)

        # Commit to git
        logger.info(f'[{job_id}] Committing to git...')
        commit_to_git(filename, job_id)

        # Trigger build and deploy
        logger.info(f'[{job_id}] Building and deploying...')
        build_and_deploy(job_id)

        logger.info(f'[{job_id}] Publishing complete!')

    except Exception as e:
        logger.error(f'[{job_id}] Publishing error: {e}')
        raise


def copy_photos_to_public(photo_paths: list, job_id: str, timestamp: datetime):
    """Copy photos to Astro public directory"""
    try:
        year = timestamp.strftime('%Y')
        month = timestamp.strftime('%m')
        day = timestamp.strftime('%d')

        dest_dir = f'{ASTRO_REPO}/public/images/tour/{year}/{month}/{day}'
        os.makedirs(dest_dir, exist_ok=True)

        copied_paths = []
        for i, photo_path in enumerate(photo_paths):
            if os.path.exists(photo_path):
                dest_path = f'{dest_dir}/photo_{i+1}.jpg'
                shutil.copy2(photo_path, dest_path)
                logger.info(f'[{job_id}] Copied: {photo_path} → {dest_path}')
                copied_paths.append(dest_path)

        return copied_paths

    except Exception as e:
        logger.error(f'[{job_id}] Photo copy error: {e}')
        raise


def commit_to_git(filename: str, job_id: str):
    """Commit blog entry to git"""
    try:
        os.chdir(ASTRO_REPO)

        # Add files
        subprocess.run(['git', 'add', f'src/content/blog/{filename}'], check=True)
        subprocess.run(['git', 'add', 'public/images/tour/'], check=True)

        # Commit
        commit_msg = f'feat: add tour blog entry {filename}'
        subprocess.run(['git', 'commit', '-m', commit_msg], check=True)

        logger.info(f'[{job_id}] Committed to git')

    except subprocess.CalledProcessError as e:
        logger.error(f'[{job_id}] Git commit error: {e}')
        raise


def build_and_deploy(job_id: str):
    """Build Astro site and deploy to IONOS"""
    try:
        os.chdir(ASTRO_REPO)

        # Build
        logger.info(f'[{job_id}] Building Astro site...')
        subprocess.run(['npm', 'run', 'build'], check=True)

        # Deploy (run upload script)
        logger.info(f'[{job_id}] Deploying to IONOS...')
        subprocess.run(['bash', '/tmp/sftp_upload.sh'], check=True, timeout=300)

        logger.info(f'[{job_id}] Deployment complete')

    except subprocess.CalledProcessError as e:
        logger.error(f'[{job_id}] Build/deploy error: {e}')
        raise
