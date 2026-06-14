import os
import logging
from datetime import datetime
import gpxpy
import whisper
import requests
import json

logger = logging.getLogger(__name__)

# Ollama endpoint
OLLAMA_HOST = os.getenv('OLLAMA_HOST', 'http://192.168.178.214:11434')
OLLAMA_MODEL = 'qwen2.5:7b-instruct-q4_K_M'

# Load Whisper model once at startup
whisper_model = None

def get_whisper_model():
    global whisper_model
    if whisper_model is None:
        logger.info('Loading Whisper model (first time only)...')
        whisper_model = whisper.load_model('base')
        logger.info('Whisper model loaded')
    return whisper_model

def call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Call Ollama API for text generation"""
    try:
        response = requests.post(
            f'{OLLAMA_HOST}/api/generate',
            json={
                'model': model,
                'prompt': prompt,
                'stream': False,
                'temperature': 0.7
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()['response']
    except Exception as e:
        logger.error(f'Ollama error: {e}')
        raise


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

        # Step 3: Rewrite with Ollama (matching Belgium tour style)
        logger.info(f'[{job_id}] Rewriting with Ollama...')
        blog_content = await rewrite_with_ollama(
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
    """Transcribe voice file to text using local Whisper"""
    try:
        logger.info(f'Transcribing: {voice_file_path}')
        model = get_whisper_model()
        result = model.transcribe(voice_file_path, language='de')
        return result['text']
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


async def rewrite_with_ollama(transcription: str, route_stats: dict) -> str:
    """
    Rewrite voice transcription into a polished blog entry using Ollama
    Matches Belgium tour voice style
    """

    style_context = """Du bist ein erfahrener Reiseblogger, der Fahrradtouren dokumentiert.
    Schreibe im Stil der bestehenden Belgien-Touren-Einträge:

    - Persönlich, Ich-Perspektive
    - Mischung aus praktischen Details und emotionalen Reflexionen
    - Lockerer Ton mit Humor und Selbstironie ("Eieiei", "Und los geht's!")
    - Beobachtungen zur Landschaft
    - Herausforderungs-Lösungs-Ansatz
    - Ellipsen (...) für Nachdruck
    - Ausrufezeichen für Überraschung
    - Spezifische Details (Essen, Orte, Begegnungen)
    - Wetterbeschreibungen
    - Körperliche Empfindungen
    - Reflexion über Erfolge und Lernen

    Schreibe 400-600 Wörter, natürlich und lesbar.
    Beginne mit einem ansprechenden Hook.
    Integriere die Route-Statistiken natürlich in den Text.
    """

    route_info = f"""Routen-Statistiken:
- Distanz: {route_stats['distance_km']} km
- Höhenmeter: {route_stats['elevation_gain_m']} m
- Abstieg: {route_stats['elevation_loss_m']} m"""

    prompt = f"""{style_context}

Rohe Transkription:
{transcription}

{route_info}

Schreibe jetzt einen polierte Blog-Eintrag basierend auf dieser Transkription.
Behalte die authentische Stimme bei und verbessere Klarheit und Fluss."""

    try:
        logger.info('Rewriting with Ollama...')
        response = call_ollama(prompt)
        return response
    except Exception as e:
        logger.error(f'Ollama rewrite error: {e}')
        raise


async def generate_title(transcription: str, route_stats: dict) -> str:
    """Generate blog entry title using Ollama"""
    prompt = f"""Basierend auf dieser Zusammenfassung und den Routen-Statistiken,
    erzeuge einen kurzen, ansprechenden deutschen Blog-Titel (5-8 Wörter).

    Zusammenfassung: {transcription[:200]}...
    Distanz: {route_stats['distance_km']} km

    Gib nur den Titel zurück, sonst nichts."""

    try:
        response = call_ollama(prompt)
        return response.strip()
    except Exception as e:
        logger.error(f'Title generation error: {e}')
        return f"Bikepacking Etappe {datetime.now().strftime('%d.%m.%Y')}"
