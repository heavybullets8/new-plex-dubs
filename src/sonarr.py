"""Sonarr webhook handler for managing anime episode collections."""

from __future__ import annotations

from typing import Any
import time
import threading

from flask import Request
from plexapi.exceptions import NotFound  # type: ignore[import-untyped]
from plexapi.video import Episode, Show  # type: ignore[import-untyped]

from .config import app, plex, SONARR_LIBRARY
from .shared import (
    is_english_dubbed,
    manage_collection,
    handle_deletion_event,
    is_recent_or_upcoming_release,
    was_media_deleted,
    get_fuzzy_match,
)


def get_episode_from_data(
    LIBRARY_NAME: str,
    show_name: str,
    season_number: int,
    episode_number: int,
    max_retries: int = 3,
    delay: int = 10
) -> Episode | None:
    """Retrieve an episode from Plex with retry logic and fuzzy matching.

    Args:
        LIBRARY_NAME: Name of the Plex library section.
        show_name: Name of the show.
        season_number: Season number.
        episode_number: Episode number.
        max_retries: Maximum number of retry attempts.
        delay: Delay in seconds between retries.

    Returns:
        Episode object if found, None otherwise.
    """
    app.logger.info(f"Attempting to find show '{show_name}' in Plex...")
    library_section = plex.library.section(LIBRARY_NAME)  # type: ignore[no-untyped-call]
    retries: int = 0
    show: Show | None = None

    while retries < max_retries and not show:
        try:
            potential_matches: list[Show] = library_section.search(title=show_name)  # type: ignore[assignment]

            # Check for 100% match
            exact_match: Show | None = next(
                (match for match in potential_matches if match.title == show_name),
                None
            )
            if exact_match:
                show = exact_match
                app.logger.info(f"Exact match found: {show.title}")
                break

            app.logger.info(f"No exact match found for '{show_name}'. Retrying...")
            time.sleep(delay)
        except NotFound:
            app.logger.info(f"Show '{show_name}' not found. Retrying...")
            time.sleep(delay)

        retries += 1

    # Fallback to fuzzy matching
    if not show:
        app.logger.info(f"Attempting fuzzy match for show '{show_name}'.")
        fuzzy_result = get_fuzzy_match(library_section, show_name)
        if fuzzy_result and isinstance(fuzzy_result, Show):
            show = fuzzy_result
            app.logger.info(f"Found show by fuzzy match: {show.title}")
        else:
            app.logger.error(f"Show '{show_name}' not found in Plex after retries and fuzzy match.")
            return None

    # Try to find the episode
    app.logger.info(f"Verifying the episode for '{show.title}' is in Plex...")
    retries = 0
    while retries < max_retries:
        try:
            episode: Episode = show.episode(season=season_number, episode=episode_number)  # type: ignore[assignment]
            app.logger.info(f"Found episode by season and number: {episode.title}")
            return episode
        except NotFound:
            app.logger.info("Episode not found. Retrying...")
            time.sleep(delay)
        except Exception as e:
            app.logger.error(f"Error fetching episode by season and number: {e}")
        retries += 1

    app.logger.error(
        f"Episode for Season {season_number}, Episode {episode_number} not found in '{show.title}' after retries."
    )
    return None


def sonarr_handle_download_event(
    LIBRARY_NAME: str,
    show_name: str,
    season_number: int,
    episode_number: int
) -> None:
    """Handle a download event from Sonarr.

    Args:
        LIBRARY_NAME: Name of the Plex library section.
        show_name: Name of the show.
        season_number: Season number.
        episode_number: Episode number.
    """
    try:
        episode: Episode | None = get_episode_from_data(
            LIBRARY_NAME, show_name, season_number, episode_number, max_retries=3, delay=10
        )
        if episode:
            manage_collection(LIBRARY_NAME, episode)
    except Exception as e:
        app.logger.error(f"Error processing request: {e}")


def process_download_event(
    library_name: str,
    show_name: str,
    episode_name: str,
    episode_id: int,
    season_number: int,
    episode_number: int,
    is_upgrade: bool,
    is_recent_release: bool
) -> None:
    """Process a download event and start collection management if criteria are met.

    Args:
        library_name: Name of the Plex library section.
        show_name: Name of the show.
        episode_name: Name of the episode.
        episode_id: Episode ID.
        season_number: Season number.
        episode_number: Episode number.
        is_upgrade: Whether this is an upgrade.
        is_recent_release: Whether this is a recent release.
    """
    if is_upgrade:
        app.logger.info(f"Processing upgrade for: {show_name} - {episode_name} (ID: {episode_id})")
    elif is_recent_release:
        app.logger.info(f"Processing recent release for: {show_name} - {episode_name} (ID: {episode_id})")
    else:
        app.logger.info(
            f"Skipping: {show_name} - {episode_name} (ID: {episode_id}) - Not an upgrade or recent release"
        )
        return

    threading.Thread(
        target=sonarr_handle_download_event,
        args=(library_name, show_name, season_number, episode_number)
    ).start()


def sonarr_log_event_details(
    event_type: str,
    show_name: str,
    episode_name: str,
    episode_id: int,
    is_dubbed: bool,
    is_upgrade: bool,
    air_date: str | None,
    season_number: int,
    episode_number: int
) -> None:
    """Log details about a Sonarr webhook event.

    Args:
        event_type: Type of the webhook event.
        show_name: Name of the show.
        episode_name: Name of the episode.
        episode_id: Episode ID.
        is_dubbed: Whether the episode is dubbed.
        is_upgrade: Whether this is an upgrade.
        air_date: Air date of the episode.
        season_number: Season number.
        episode_number: Episode number.
    """
    app.logger.info(" ")
    app.logger.info("Sonarr Webhook Received")
    app.logger.info(f"Event Type: {event_type}")
    app.logger.info(f"Show Title: {show_name}")
    app.logger.info(f"Episode: {episode_name} - ID: {episode_id}")
    app.logger.info(f"Season: {season_number}")
    app.logger.info(f"Episode: {episode_number}")
    app.logger.info(f"Air Date: {air_date}")
    app.logger.info(f"English Dubbed: {is_dubbed}")
    app.logger.info(f"Is Upgrade: {is_upgrade}")


def sonarr_webhook(request: Request) -> tuple[str, int]:
    """Handle incoming Sonarr webhook requests.

    Args:
        request: Flask request object.

    Returns:
        Tuple of (response message, status code).
    """
    data: dict[str, Any] = request.get_json()
    event_type: str = data.get('eventType', '')
    show_name: str = data.get('series', {}).get('title', '')
    episode_name: str = data.get('episodes', [{}])[0].get('title', '')
    episode_id: int = data.get('episodes', [{}])[0].get('id', 0)
    season_number: int = data.get('episodes', [{}])[0].get('seasonNumber', 0)
    episode_number: int = data.get('episodes', [{}])[0].get('episodeNumber', 0)
    air_date: str | None = data.get('episodes', [{}])[0].get('airDate')
    is_dubbed: bool = is_english_dubbed(data)
    is_upgrade: bool = data.get('isUpgrade', False)

    is_recent_release: bool = is_recent_or_upcoming_release(air_date)

    sonarr_log_event_details(
        event_type, show_name, episode_name, episode_id, is_dubbed,
        is_upgrade, air_date, season_number, episode_number
    )

    if event_type == 'EpisodeFileDelete' and data.get('deleteReason') == 'upgrade' and is_dubbed:
        handle_deletion_event(episode_id)
    elif was_media_deleted(episode_id):
        app.logger.info("Skipping as it was a previous upgrade of an English dubbed episode.")
    elif event_type == 'Download' and is_dubbed and SONARR_LIBRARY:
        process_download_event(
            SONARR_LIBRARY, show_name, episode_name, episode_id,
            season_number, episode_number, is_upgrade, is_recent_release
        )
    else:
        app.logger.info("Skipping: does not meet criteria for processing.")

    return "Webhook received", 200
