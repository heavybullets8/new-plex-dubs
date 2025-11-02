"""Sonarr webhook handler for managing anime episode collections."""

from __future__ import annotations

from typing import Any
import time
import threading

from flask import Request
from plexapi.exceptions import NotFound  # type: ignore[import-untyped]
from plexapi.video import Episode, Show  # type: ignore[import-untyped]

from .config import app, plex, SONARR_LIBRARY
from .logger import log_event, log_action, log_error
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
    log_action(app.logger, "fetch_show", show=show_name, library=LIBRARY_NAME, status="searching")
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
                log_action(app.logger, "fetch_show", show=show.title, status="found", match_type="exact")
                break

            time.sleep(delay)
        except NotFound:
            time.sleep(delay)

        retries += 1

    # Fallback to fuzzy matching
    if not show:
        fuzzy_result = get_fuzzy_match(library_section, show_name)
        if fuzzy_result and isinstance(fuzzy_result, Show):
            show = fuzzy_result
            log_action(app.logger, "fetch_show", show=show.title, status="found", match_type="fuzzy")
        else:
            log_error(app.logger, "Show not found", show=show_name, attempts=max_retries)
            return None

    # Try to find the episode
    log_action(app.logger, "fetch_episode", show=show.title, season=season_number, episode=episode_number, status="searching")
    retries = 0
    while retries < max_retries:
        try:
            episode: Episode = show.episode(season=season_number, episode=episode_number)  # type: ignore[assignment]
            log_action(app.logger, "fetch_episode", episode=episode.title, status="found")
            return episode
        except NotFound:
            time.sleep(delay)
        except Exception as e:
            log_error(app.logger, "Error fetching episode", exception=str(e), season=season_number, episode=episode_number)
        retries += 1

    log_error(
        app.logger, "Episode not found after retries",
        show=show.title, season=season_number, episode=episode_number, attempts=max_retries
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
        log_error(app.logger, "Error processing download event", exception=str(e), library=LIBRARY_NAME)


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
        log_action(
            app.logger, "process_upgrade",
            show=show_name, episode=episode_name, episode_id=episode_id
        )
    elif is_recent_release:
        log_action(
            app.logger, "process_recent_release",
            show=show_name, episode=episode_name, episode_id=episode_id
        )
    else:
        log_action(
            app.logger, "skip_episode",
            show=show_name, episode=episode_name, episode_id=episode_id,
            reason="not upgrade or recent release"
        )
        return

    threading.Thread(
        target=sonarr_handle_download_event,
        args=(library_name, show_name, season_number, episode_number)
    ).start()


def sonarr_log_webhook(
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
    """Log details about a Sonarr webhook event in structured format.

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
    log_event(
        app.logger, "webhook",
        source="sonarr",
        event_type=event_type,
        show=show_name,
        episode=episode_name,
        episode_id=episode_id,
        season=season_number,
        ep_num=episode_number,
        air_date=air_date if air_date else "unknown",
        dubbed=is_dubbed,
        upgrade=is_upgrade
    )


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

    sonarr_log_webhook(
        event_type, show_name, episode_name, episode_id, is_dubbed,
        is_upgrade, air_date, season_number, episode_number
    )

    if event_type == 'EpisodeFileDelete' and data.get('deleteReason') == 'upgrade' and is_dubbed:
        handle_deletion_event(episode_id)
    elif was_media_deleted(episode_id):
        log_action(app.logger, "skip_episode", reason="previous upgrade of dubbed episode", episode_id=episode_id)
    elif event_type == 'Download' and is_dubbed and SONARR_LIBRARY:
        process_download_event(
            SONARR_LIBRARY, show_name, episode_name, episode_id,
            season_number, episode_number, is_upgrade, is_recent_release
        )
    else:
        log_action(app.logger, "skip_episode", reason="does not meet criteria", event=event_type, dubbed=is_dubbed)

    return "Webhook received", 200
