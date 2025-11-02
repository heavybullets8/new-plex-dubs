"""Shared utilities for Plex collection management."""

from __future__ import annotations

from typing import Any
import datetime
import fcntl

from rapidfuzz import process
from plexapi.video import Episode, Movie  # type: ignore[import-untyped]
from plexapi.library import LibrarySection  # type: ignore[import-untyped]

from .config import app, plex, MAX_COLLECTION_SIZE, MAX_DATE_DIFF


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
        app.logger.info(f"No close match found for '{query_title}' with cutoff score of {score_cutoff}.")
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
    app.logger.info(f"Managing and sorting collection for {media_type}: {media.title}")
    collection = None

    # Check if collection exists and retrieve it
    for col in plex.library.section(LIBRARY_NAME).collections():
        if col.title == collection_name:
            collection = col
            app.logger.info(f"Collection '{collection_name}' exists.")
            break

    # Create collection if it doesn't exist
    if collection is None:
        app.logger.info(f"Creating new collection '{collection_name}'.")
        collection = plex.library.section(LIBRARY_NAME).createCollection(title=collection_name, items=[media])
        # Set collection sort
        collection.sortUpdate(sort="custom")
        return

    # Add media to collection if not present
    if media not in collection.items():
        app.logger.info(f"Adding {media_type} '{media.title}' to collection '{collection_name}'.")
        collection.addItems([media])
        # Move the media to the front of the collection
        collection.moveItem(media, after=None)
        app.logger.info(f"Moved {media_type} '{media.title}' to the front of collection.")
    else:
        app.logger.info(f"{media_type} '{media.title}' already in collection.")

    # Check if the collection size exceeds the maximum allowed
    if len(collection.items()) >= MAX_COLLECTION_SIZE:
        app.logger.info("Trimming the collection to the maximum allowed size...")

        items = collection.items()
        num_items_to_remove: int = len(items) - MAX_COLLECTION_SIZE
        # Select items to be removed based on the collection exceeding the MAX_COLLECTION_SIZE
        items_to_remove = items[-num_items_to_remove:]

        # Log the titles of the items that are to be removed
        for item in items_to_remove:
            app.logger.info(f"Removing item: '{item.title}' from the collection.")

        # Remove the identified items from the collection
        collection.removeItems(items_to_remove)


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
            app.logger.info(f"Added {media_id} to deletion record.")
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
        app.logger.warning(f"Invalid date format: {date_str}")
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
