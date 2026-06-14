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
    1. Create markdown file
    2. Copy photos to public directory
    3. Commit to git
    4. Trigger build and deploy
    """
    try:
        logger.info(f'[{job_id}] Publishing blog entry...')

        # Generate filename (tour-etappe-YYYY-MM-DD)
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f'bikepacking-tour-{today}.md'
        filepath = f'{BLOG_DIR}/{filename}'

        # Create frontmatter
        photos_list = job['photos'].split(',') if job['photos'] else []
        hero_image = photos_list[0] if photos_list else '/images/blog/default.jpg'

        frontmatter = {
            'title': job.get('blog_file', f'Bikepacking {today}'),
            'date': today,
            'category': 'biketour',
            'heroImage': hero_image,
            'images': photos_list
        }

        # Create markdown content
        markdown_content = f"""---
title: "{frontmatter['title']}"
date: {frontmatter['date']}
category: {frontmatter['category']}
heroImage: "{frontmatter['heroImage']}"
images:
{chr(10).join(f'  - "{img}"' for img in frontmatter['images'])}
---

## {frontmatter['title']}

{job['transcription']}

"""

        # Write markdown file
        with open(filepath, 'w') as f:
            f.write(markdown_content)

        logger.info(f'[{job_id}] Blog file created: {filepath}')

        # Copy photos to public directory
        logger.info(f'[{job_id}] Copying photos...')
        copy_photos_to_public(photos_list, job_id)

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


def copy_photos_to_public(photo_paths: list, job_id: str):
    """Copy photos to Astro public directory"""
    try:
        today = datetime.now()
        year = today.strftime('%Y')
        month = today.strftime('%m')
        day = today.strftime('%d')

        dest_dir = f'{ASTRO_REPO}/public/images/blog/{year}/{month}/{day}'
        os.makedirs(dest_dir, exist_ok=True)

        for i, photo_path in enumerate(photo_paths):
            if os.path.exists(photo_path):
                dest_path = f'{dest_dir}/photo_{i+1}.jpg'
                shutil.copy2(photo_path, dest_path)
                logger.info(f'[{job_id}] Copied: {photo_path} → {dest_path}')

    except Exception as e:
        logger.error(f'[{job_id}] Photo copy error: {e}')
        raise


def commit_to_git(filename: str, job_id: str):
    """Commit blog entry to git"""
    try:
        os.chdir(ASTRO_REPO)

        # Add files
        subprocess.run(['git', 'add', f'src/content/blog/{filename}'], check=True)
        subprocess.run(['git', 'add', 'public/images/blog/'], check=True)

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
