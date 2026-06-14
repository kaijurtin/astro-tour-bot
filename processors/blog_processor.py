import os
import logging
from datetime import datetime
import gpxpy
from openai import OpenAI
from anthropic import Anthropic

logger = logging.getLogger(__name__)

# Initialize API clients (lazy load to allow startup without keys)
openai_client = None
anthropic_client = None

def get_openai_client():
    global openai_client
    if openai_client is None:
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set in .env")
        openai_client = OpenAI(api_key=api_key)
    return openai_client

def get_anthropic_client():
    global anthropic_client
    if anthropic_client is None:
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set in .env")
        anthropic_client = Anthropic(api_key=api_key)
    return anthropic_client


async def process_tour_input(job_id: str, job_data: dict) -> tuple:
    """
    Process voice input into a blog entry:
    1. Transcribe voice with Whisper
    2. Parse GPX for route data
    3. Rewrite with Claude (in user's voice)
    4. Generate blog title
    """
    try:
        # Step 1: Transcribe voice
        logger.info(f'[{job_id}] Transcribing voice...')
        transcription = await transcribe_voice(job_data['voice'])
        logger.info(f'[{job_id}] Transcription complete: {len(transcription)} chars')

        # Step 2: Parse GPX for route stats
        logger.info(f'[{job_id}] Parsing GPX...')
        route_stats = parse_gpx(job_data['gpx'])
        logger.info(f'[{job_id}] Route stats: {route_stats}')

        # Step 3: Rewrite with Claude (matching Belgium tour style)
        logger.info(f'[{job_id}] Rewriting with Claude...')
        blog_content = await rewrite_with_claude(
            transcription=transcription,
            route_stats=route_stats
        )
        logger.info(f'[{job_id}] Rewrite complete: {len(blog_content)} chars')

        # Step 4: Generate title
        blog_title = await generate_title(transcription, route_stats)

        return blog_content, blog_title

    except Exception as e:
        logger.error(f'[{job_id}] Processing error: {e}')
        raise


async def transcribe_voice(voice_file_path: str) -> str:
    """Transcribe voice file to text using OpenAI Whisper"""
    try:
        with open(voice_file_path, 'rb') as audio_file:
            response = get_openai_client().audio.transcriptions.create(
                model='whisper-1',
                file=audio_file,
                language='de'  # German
            )
        return response.text
    except Exception as e:
        logger.error(f'Transcription error: {e}')
        raise


def parse_gpx(gpx_file_path: str) -> dict:
    """Parse GPX file and extract route statistics"""
    try:
        with open(gpx_file_path, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)

        # Calculate stats
        distance_km = gpx.length_3d() / 1000
        elevation_gain = 0
        elevation_loss = 0

        for track in gpx.tracks:
            for segment in track.segments:
                for i in range(len(segment.points) - 1):
                    p1 = segment.points[i]
                    p2 = segment.points[i + 1]
                    if p1.elevation and p2.elevation:
                        diff = p2.elevation - p1.elevation
                        if diff > 0:
                            elevation_gain += diff
                        else:
                            elevation_loss += abs(diff)

        # Get start/end points
        start_point = None
        end_point = None
        if gpx.tracks:
            first_track = gpx.tracks[0]
            if first_track.segments:
                first_segment = first_track.segments[0]
                if first_segment.points:
                    start_point = first_segment.points[0]
                    end_point = first_segment.points[-1]

        return {
            'distance_km': round(distance_km, 1),
            'elevation_gain_m': round(elevation_gain),
            'elevation_loss_m': round(elevation_loss),
            'start_point': (start_point.latitude, start_point.longitude) if start_point else None,
            'end_point': (end_point.latitude, end_point.longitude) if end_point else None,
            'gpx_path': gpx_file_path
        }
    except Exception as e:
        logger.error(f'GPX parsing error: {e}')
        raise


async def rewrite_with_claude(transcription: str, route_stats: dict) -> str:
    """
    Rewrite voice transcription into a polished blog entry
    in the user's style (matching Belgium tour voice)
    """

    style_context = """You are rewriting a bicycle tour blog entry in German.
    The style should match these characteristics from existing Belgium tour entries:

    - Conversational, personal, first-person narrative
    - Mix of practical details and emotional reflections
    - Casual tone with humor and self-deprecation (e.g., "Eieiei", "Und los geht's!")
    - Observations about landscape and surroundings
    - Challenge-and-solution approach to obstacles
    - Use of ellipsis (...) for emphasis and trailing thoughts
    - Exclamation marks for excitement or surprise
    - Specific details about food, locations, people encountered
    - Weather descriptions
    - Physical sensations and body awareness (fatigue, soreness, etc.)
    - Reflection on the day's achievements and learning

    The entry should be 400-600 words, natural and readable.
    Start with an engaging hook about the day.
    Include the route statistics naturally in the narrative.
    """

    route_info = f"""
    Route statistics for this day:
    - Distance: {route_stats['distance_km']} km
    - Elevation gain: {route_stats['elevation_gain_m']} m
    - Elevation loss: {route_stats['elevation_loss_m']} m
    """

    prompt = f"""{style_context}

    Voice transcription (raw):
    {transcription}

    {route_info}

    Please rewrite this into a polished blog entry that captures the voice and style.
    Make it engaging, personal, and true to the transcription while improving clarity and flow.
    """

    try:
        message = get_anthropic_client().messages.create(
            model='claude-opus-4-1',
            max_tokens=1024,
            messages=[
                {'role': 'user', 'content': prompt}
            ]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f'Claude rewrite error: {e}')
        raise


async def generate_title(transcription: str, route_stats: dict) -> str:
    """Generate blog entry title"""
    prompt = f"""Based on this bicycle tour day summary and route stats,
    generate a short, engaging German blog title (5-8 words).

    Summary: {transcription[:200]}...
    Distance: {route_stats['distance_km']} km

    Return only the title, nothing else."""

    try:
        message = get_anthropic_client().messages.create(
            model='claude-opus-4-1',
            max_tokens=100,
            messages=[
                {'role': 'user', 'content': prompt}
            ]
        )
        return message.content[0].text.strip()
    except Exception as e:
        logger.error(f'Title generation error: {e}')
        return f"Bikepacking Etappe {datetime.now().strftime('%d.%m.%Y')}"
