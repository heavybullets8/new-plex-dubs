"""Main Flask application for Plex Dubs webhook handler."""

from flask import request
from src.config import app, ensure_file_exists
from src.sonarr import sonarr_webhook
from src.radarr import radarr_webhook

ensure_file_exists("/tmp/deleted_media_ids.txt")


@app.route('/sonarr', methods=['POST'])
def handle_sonarr() -> tuple[str, int]:
    """Handle Sonarr webhook requests.

    Returns:
        Tuple of (response message, status code).
    """
    return sonarr_webhook(request)


@app.route('/radarr', methods=['POST'])
def handle_radarr() -> tuple[str, int]:
    """Handle Radarr webhook requests.

    Returns:
        Tuple of (response message, status code).
    """
    return radarr_webhook(request)
