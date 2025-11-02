"""Radarr webhook handler for managing anime movie collections."""

from __future__ import annotations

from typing import Any
import threading

from flask import Request
from plexapi.video import Movie  # type: ignore[import-untyped]

from .config import app, plex, RADARR_LIBRARY
from .logger import log_event, log_action, log_error
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
    log_action(app.logger, "fetch_movie", movie=movie_title, library=LIBRARY_NAME, status="searching")
    try:
        library = plex.library.section(LIBRARY_NAME)  # type: ignore[no-untyped-call]
        fuzzy_result = get_fuzzy_match(library, movie_title)  # type: ignore[arg-type]

        if fuzzy_result and isinstance(fuzzy_result, Movie):
            movie: Movie = fuzzy_result
            log_action(app.logger, "fetch_movie", movie=movie.title, status="found")
            return movie
        else:
            log_error(app.logger, "Movie not found", movie=movie_title, library=LIBRARY_NAME)
            return None
    except Exception as e:
        log_error(app.logger, "Error searching for movie", exception=str(e), movie=movie_title)
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
        log_error(app.logger, "Error processing download event", exception=str(e), library=LIBRARY_NAME)


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
        log_action(app.logger, "process_upgrade", movie=movie_title, movie_id=movie_id)
    elif is_recent_release:
        log_action(app.logger, "process_recent_release", movie=movie_title, movie_id=movie_id)
    else:
        log_action(
            app.logger, "skip_movie",
            movie=movie_title, movie_id=movie_id,
            reason="not upgrade or recent release"
        )
        return

    threading.Thread(target=radarr_handle_download_event, args=(library_name, movie_title)).start()


def radarr_log_webhook(
    event_type: str,
    movie_title: str,
    movie_id: int,
    release_date: str | None,
    is_dubbed: bool,
    is_upgrade: bool
) -> None:
    """Log details about a Radarr webhook event in structured format.

    Args:
        event_type: Type of the webhook event.
        movie_title: Title of the movie.
        movie_id: Movie ID.
        release_date: Release date of the movie.
        is_dubbed: Whether the movie is dubbed.
        is_upgrade: Whether this is an upgrade.
    """
    log_event(
        app.logger, "webhook",
        source="radarr",
        event_type=event_type,
        movie=movie_title,
        movie_id=movie_id,
        release_date=release_date if release_date else "unknown",
        dubbed=is_dubbed,
        upgrade=is_upgrade
    )


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

    radarr_log_webhook(event_type, movie_title, movie_id, release_date, is_dubbed, is_upgrade)

    if event_type == 'MovieFileDelete' and data.get('deleteReason') == 'upgrade' and is_dubbed:
        handle_deletion_event(movie_id)
    elif was_media_deleted(movie_id):
        log_action(app.logger, "skip_movie", reason="previous upgrade of dubbed movie", movie_id=movie_id)
    elif event_type == 'Download' and is_dubbed and RADARR_LIBRARY:
        process_radarr_download_event(RADARR_LIBRARY, movie_title, movie_id, is_upgrade, is_recent_release)
    else:
        log_action(app.logger, "skip_movie", reason="does not meet criteria", event=event_type, dubbed=is_dubbed)

    return "Webhook received", 200
