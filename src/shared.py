"""Shared utilities for Plex collection management."""

from __future__ import annotations

from typing import Any
import datetime
import fcntl

from rapidfuzz import process
from plexapi.video import Episode, Movie  # type: ignore[import-untyped]
from plexapi.library import LibrarySection  # type: ignore[import-untyped]

from .config import app, plex, MAX_COLLECTION_SIZE, MAX_DATE_DIFF
from .logger import log_action, log_warning


def is_english_dubbed(data: dict[str, Any]) -> bool:
    """Check if media is English dubbed based on webhook data.

    Args:
        data: Webhook data from Sonarr or Radarr.

    Returns:
        True if media is English dubbed, False otherwise.
    """
    audio_languages: list[str] = data.get('episodeFile', {}).get('mediaInfo', {}).get('audioLanguages', [])
    if not audio_languages:
        audio_languages = data.get('movieFile', {}).get('mediaInfo', {}).get('audioLanguages', [])
    is_dubbed_audio: bool = 'eng' in audio_languages

    custom_formats: list[dict[str, Any]] = data.get('customFormatInfo', {}).get('customFormats', [])
    is_custom_format: bool = any(cf.get('name') in ['Anime Dual Audio', 'Dubs Only'] for cf in custom_formats)

    return is_dubbed_audio or is_custom_format


def get_fuzzy_match(
    library_section: LibrarySection,
    query_title: str,
    score_cutoff: int = 75
) -> Episode | Movie | None:
    """Find the closest matching media item using fuzzy matching.

    Args:
        library_section: Plex library section to search.
        query_title: Title to search for.
        score_cutoff: Minimum score for a match (0-100).

    Returns:
        The closest matching media item, or None if no match above threshold.
    """
    items: list[Episode | Movie] = library_section.all()  # type: ignore[assignment]
    titles: list[str] = [item.title for item in items]  # type: ignore[misc]

    result = process.extractOne(query_title, titles, score_cutoff=score_cutoff)

    if result and result[1] >= score_cutoff:
        matched_title: str = result[0]
        return library_section.get(matched_title)
    else:
        log_action(app.logger, "fuzzy_match_failed", query=query_title, cutoff=score_cutoff)
        return None


def manage_collection(
    LIBRARY_NAME: str,
    media: Episode | Movie,
    collection_name: str = 'Latest Dubs',
    is_movie: bool = False
) -> None:
    """Manage and sort a Plex collection, adding media and trimming if necessary.

    Args:
        LIBRARY_NAME: Name of the Plex library.
        media: The Episode or Movie object to add to the collection.
        collection_name: Name of the collection to manage.
        is_movie: Whether the media is a movie (vs episode).
    """
    media_type: str = 'movie' if is_movie else 'episode'
    collection = None

    # Check if collection exists and retrieve it
    for col in plex.library.section(LIBRARY_NAME).collections():
        if col.title == collection_name:
            collection = col
            break

    # Create collection if it doesn't exist
    if collection is None:
        log_action(app.logger, "create_collection", collection=collection_name, media=media.title, media_type=media_type)
        collection = plex.library.section(LIBRARY_NAME).createCollection(title=collection_name, items=[media])
        collection.sortUpdate(sort="custom")
        return

    # Add media to collection if not present
    if media not in collection.items():
        collection.addItems([media])
        collection.moveItem(media, after=None)
        log_action(
            app.logger, "add_to_collection",
            media=media.title, media_type=media_type,
            collection=collection_name, status="added_to_front"
        )
    else:
        log_action(
            app.logger, "skip_duplicate",
            media=media.title, media_type=media_type,
            collection=collection_name, reason="already in collection"
        )

    # Check if the collection size exceeds the maximum allowed
    current_size = len(collection.items())
    if current_size >= MAX_COLLECTION_SIZE:
        items = collection.items()
        num_items_to_remove: int = current_size - MAX_COLLECTION_SIZE
        items_to_remove = items[-num_items_to_remove:]

        removed_titles = [item.title for item in items_to_remove]  # type: ignore[misc]
        collection.removeItems(items_to_remove)

        log_action(
            app.logger, "trim_collection",
            collection=collection_name,
            removed_count=num_items_to_remove,
            new_size=MAX_COLLECTION_SIZE,
            removed_items=", ".join(removed_titles[:3]) + ("..." if len(removed_titles) > 3 else "")
        )


def trim_file(file_path: str, max_entries: int) -> None:
    """Trim a file to keep only the last N entries.

    Args:
        file_path: Path to the file to trim.
        max_entries: Maximum number of entries to keep.
    """
    with open(file_path, "r+") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        lines: list[str] = file.readlines()
        if len(lines) > max_entries:
            file.seek(0)
            file.truncate()
            file.writelines(lines[-max_entries:])  # Keep only the last max_entries
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def handle_deletion_event(media_id: int) -> None:
    """Record a media deletion event to prevent re-adding on upgrade.

    Args:
        media_id: ID of the deleted media.
    """
    with open("/tmp/deleted_media_ids.txt", "a+") as file:
        fcntl.flock(file.fileno(), fcntl.LOCK_EX)
        file.seek(0)  # Go to the beginning of the file
        if str(media_id) not in file.read():
            file.write(f"{media_id}\n")
            log_action(app.logger, "record_deletion", media_id=media_id, status="recorded")
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)

    trim_file("/tmp/deleted_media_ids.txt", 100)  # Limit to 100 entries


def is_recent_or_upcoming_release(date_str: str | None) -> bool:
    """Check if a release date is recent or upcoming.

    Args:
        date_str: Date string in 'YYYY-MM-DD' format.

    Returns:
        True if the date is within MAX_DATE_DIFF days or in the future.
    """
    if not date_str:
        return False

    try:
        release_or_air_date: datetime.date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        log_warning(app.logger, "Invalid date format", date=date_str)
        return False

    current_date: datetime.date = datetime.datetime.now(datetime.UTC).date()
    days_diff: int = (current_date - release_or_air_date).days
    return 0 <= days_diff <= MAX_DATE_DIFF or release_or_air_date > current_date


def was_media_deleted(media_id: int) -> bool:
    """Check if a media ID was previously deleted.

    Args:
        media_id: ID of the media to check.

    Returns:
        True if the media was previously deleted, False otherwise.
    """
    try:
        with open("/tmp/deleted_media_ids.txt", "r") as file:
            fcntl.flock(file.fileno(), fcntl.LOCK_SH)
            deleted_ids: list[str] = file.read().splitlines()
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)

        return str(media_id) in deleted_ids
    except FileNotFoundError:
        return False
