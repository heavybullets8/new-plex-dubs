"""Radarr webhook handler for managing anime movie collections."""

from __future__ import annotations

from typing import Any
import threading

from flask import Request
from plexapi.video import Movie  # type: ignore[import-untyped]

from .config import app, plex, RADARR_LIBRARY
from .shared import (
    is_english_dubbed,
    manage_collection,
    is_recent_or_upcoming_release,
    handle_deletion_event,
    was_media_deleted,
    get_fuzzy_match,
)


def get_movie_from_data(LIBRARY_NAME: str, movie_title: str) -> Movie | None:
    """Retrieve a movie from Plex using fuzzy matching.

    Args:
        LIBRARY_NAME: Name of the Plex library section.
        movie_title: Title of the movie to search for.

    Returns:
        Movie object if found, None otherwise.
    """
    app.logger.info(f"Searching for movie '{movie_title}' in library.")
    try:
        library = plex.library.section(LIBRARY_NAME)  # type: ignore[no-untyped-call]
        fuzzy_result = get_fuzzy_match(library, movie_title)  # type: ignore[arg-type]

        if fuzzy_result and isinstance(fuzzy_result, Movie):
            movie: Movie = fuzzy_result
            app.logger.info(f"Found movie: {movie.title}")
            return movie
        else:
            app.logger.error(f"Movie '{movie_title}' not found in library.")
            return None
    except Exception as e:
        app.logger.error(f"Error searching for movie: {e}")
        return None


def radarr_handle_download_event(LIBRARY_NAME: str, movie_name: str) -> None:
    """Handle a download event from Radarr.

    Args:
        LIBRARY_NAME: Name of the Plex library section.
        movie_name: Name of the movie.
    """
    try:
        movie: Movie | None = get_movie_from_data(LIBRARY_NAME, movie_name)
        if movie:
            manage_collection(LIBRARY_NAME, movie, is_movie=True)
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")


def process_radarr_download_event(
    library_name: str,
    movie_title: str,
    movie_id: int,
    is_upgrade: bool,
    is_recent_release: bool
) -> None:
    """Process a download event and start collection management if criteria are met.

    Args:
        library_name: Name of the Plex library section.
        movie_title: Title of the movie.
        movie_id: Movie ID.
        is_upgrade: Whether this is an upgrade.
        is_recent_release: Whether this is a recent release.
    """
    if is_upgrade:
        app.logger.info(f"Processing upgrade for: {movie_title} (ID: {movie_id})")
    elif is_recent_release:
        app.logger.info(f"Processing recent release for: {movie_title} (ID: {movie_id})")
    else:
        app.logger.info(f"Skipping: {movie_title} (ID: {movie_id}) - Not an upgrade or recent release")
        return

    threading.Thread(target=radarr_handle_download_event, args=(library_name, movie_title)).start()


def radarr_log_event_details(
    event_type: str,
    movie_title: str,
    movie_id: int,
    release_date: str | None,
    is_dubbed: bool,
    is_upgrade: bool
) -> None:
    """Log details about a Radarr webhook event.

    Args:
        event_type: Type of the webhook event.
        movie_title: Title of the movie.
        movie_id: Movie ID.
        release_date: Release date of the movie.
        is_dubbed: Whether the movie is dubbed.
        is_upgrade: Whether this is an upgrade.
    """
    app.logger.info(" ")
    app.logger.info("Radarr Webhook Received")
    app.logger.info(f"Event Type: {event_type}")
    app.logger.info(f"Movie Title: {movie_title}")
    app.logger.info(f"Movie ID: {movie_id}")
    app.logger.info(f"Release Date: {release_date}")
    app.logger.info(f"English Dubbed: {is_dubbed}")
    app.logger.info(f"Is Upgrade: {is_upgrade}")


def radarr_webhook(request: Request) -> tuple[str, int]:
    """Handle incoming Radarr webhook requests.

    Args:
        request: Flask request object.

    Returns:
        Tuple of (response message, status code).
    """
    data: dict[str, Any] = request.get_json()
    event_type: str = data.get('eventType', '')
    movie_title: str = data.get('movie', {}).get('title', '')
    movie_id: int = data.get('movie', {}).get('id', 0)
    is_dubbed: bool = is_english_dubbed(data)
    is_upgrade: bool = data.get('isUpgrade', False)
    release_date: str | None = data.get('movie', {}).get('releaseDate')
    is_recent_release: bool = is_recent_or_upcoming_release(release_date)

    radarr_log_event_details(event_type, movie_title, movie_id, release_date, is_dubbed, is_upgrade)

    if event_type == 'MovieFileDelete' and data.get('deleteReason') == 'upgrade' and is_dubbed:
        handle_deletion_event(movie_id)
    elif was_media_deleted(movie_id):
        app.logger.info("Skipping as it was a previous upgrade of an English dubbed movie.")
    elif event_type == 'Download' and is_dubbed and RADARR_LIBRARY:
        process_radarr_download_event(RADARR_LIBRARY, movie_title, movie_id, is_upgrade, is_recent_release)
    else:
        app.logger.info("Skipping: does not meet criteria for processing.")

    return "Webhook received", 200
