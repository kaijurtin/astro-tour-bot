import os
import logging
from datetime import datetime, timedelta
import gpxpy
import json

logger = logging.getLogger(__name__)


async def process_tour_input(job_id: str, job_data: dict) -> dict:
    """
    Process voice/text input into a blog entry (raw telegraphic format):
    1. Use raw transcription from Whisper (no rewriting)
    2. Parse GPX for route data
    3. Generate simple title from transcript or default
    4. Return entry data for immediate auto-publish
    """
    try:
        # Get raw transcription
        transcription = job_data.get('transcription', '').strip()
        if not transcription:
            logger.error(f'[{job_id}] Empty transcription')
            raise ValueError('No transcription provided')

        logger.info(f'[{job_id}] Processing raw entry: {len(transcription)} chars')

        # Parse GPX for route stats
        route_stats = None
        if 'gpx' in job_data:
            logger.info(f'[{job_id}] Parsing GPX...')
            route_stats = parse_gpx(job_data['gpx'])
            logger.info(f'[{job_id}] Route stats: {route_stats}')

        # Generate simple title from first line or default
        title = generate_simple_title(transcription, route_stats)
        logger.info(f'[{job_id}] Title: {title}')

        # Calculate edit window (30 minutes from now)
        auto_published_at = datetime.now().isoformat()
        edit_window_expires = (datetime.now() + timedelta(minutes=30)).isoformat()

        # Return entry data ready for publication
        return {
            'title': title,
            'transcript': transcription,
            'route_stats': route_stats,
            'auto_published_at': auto_published_at,
            'edit_window_expires': edit_window_expires,
            'is_auto_published': True,
            'gpx_path': job_data.get('gpx'),
        }

    except Exception as e:
        logger.error(f'[{job_id}] Processing error: {e}')
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

        # Get start/end points and calculate avg speed
        start_point = None
        end_point = None
        duration_minutes = 0

        if gpx.tracks:
            first_track = gpx.tracks[0]
            if first_track.segments:
                first_segment = first_track.segments[0]
                if first_segment.points:
                    start_point = first_segment.points[0]
                    end_point = first_segment.points[-1]

                    # Calculate duration
                    if start_point.time and end_point.time:
                        duration = end_point.time - start_point.time
                        duration_minutes = duration.total_seconds() / 60

        # Calculate average speed
        avg_speed = None
        if duration_minutes > 0:
            avg_speed = round((distance_km / (duration_minutes / 60)), 1)

        return {
            'distance_km': round(distance_km, 1),
            'elevation_gain_m': round(elevation_gain),
            'elevation_loss_m': round(elevation_loss),
            'avg_speed_kmh': avg_speed,
            'start_point': (start_point.latitude, start_point.longitude) if start_point else None,
            'end_point': (end_point.latitude, end_point.longitude) if end_point else None,
            'gpx_path': gpx_file_path
        }
    except Exception as e:
        logger.error(f'GPX parsing error: {e}')
        # Return empty stats rather than failing
        return {
            'distance_km': 0,
            'elevation_gain_m': 0,
            'elevation_loss_m': 0,
            'avg_speed_kmh': None,
            'start_point': None,
            'end_point': None,
            'gpx_path': gpx_file_path
        }


def generate_simple_title(transcription: str, route_stats: dict = None) -> str:
    """
    Generate a simple title from transcript or route data.
    Follows pattern: "Tour Day N — Location" or "Etappe — Date"
    """
    try:
        # Extract first sentence for hint (max 40 chars)
        first_line = transcription.split('\n')[0].strip()
        if first_line and len(first_line) < 80:
            # Use first line if it's short enough
            if first_line.endswith('.'):
                title_hint = first_line[:-1]
            else:
                title_hint = first_line
        else:
            title_hint = None

        # Build title from available data
        date_str = datetime.now().strftime('%d.%m.%Y')

        if title_hint:
            return f"{title_hint} — {date_str}"
        elif route_stats and route_stats.get('distance_km'):
            return f"Etappe {date_str} — {route_stats['distance_km']} km"
        else:
            return f"Tour Entry {date_str}"

    except Exception as e:
        logger.error(f'Title generation error: {e}')
        return f"Tour Entry {datetime.now().strftime('%d.%m.%Y')}"
