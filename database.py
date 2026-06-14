import sqlite3
import os

DB_PATH = os.getenv('DB_PATH', '/data/tour-bot.db')

def init_db():
    """Initialize SQLite database"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Jobs table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending',
            voice_file TEXT,
            photos TEXT,
            gpx_file TEXT,
            transcription TEXT,
            blog_content TEXT,
            blog_file TEXT
        )
    ''')

    # Approvals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    ''')

    conn.commit()
    conn.close()


def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_job(user_id, voice_file=None, photos=None, gpx_file=None):
    """Create a new job record"""
    import uuid
    job_id = str(uuid.uuid4())

    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO jobs (id, user_id, voice_file, photos, gpx_file)
        VALUES (?, ?, ?, ?, ?)
    ''', (job_id, user_id, voice_file, ','.join(photos) if photos else None, gpx_file))
    db.commit()
    db.close()

    return job_id


def update_job(job_id, **kwargs):
    """Update job record"""
    db = get_db()
    cursor = db.cursor()

    for key, value in kwargs.items():
        cursor.execute(f'UPDATE jobs SET {key} = ? WHERE id = ?', (value, job_id))

    db.commit()
    db.close()


def get_job(job_id):
    """Get job by ID"""
    db = get_db()
    cursor = db.cursor()
    job = cursor.execute('SELECT * FROM jobs WHERE id = ?', (job_id,)).fetchone()
    db.close()
    return dict(job) if job else None
