"""Configuration module for Plex Dubs application."""

from __future__ import annotations

import os
import sys
import logging
import time

from flask import Flask
from plexapi.server import PlexServer  # type: ignore[import-untyped]
from urllib.parse import urlparse

app: Flask = Flask(__name__)

# Remove Flask's default handler
for handler in app.logger.handlers:
    app.logger.removeHandler(handler)

# Set up custom logging
log_handler: logging.Handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
))
app.logger.addHandler(log_handler)
app.logger.setLevel(logging.INFO)


def ensure_file_exists(file_path: str) -> None:
    """Ensure a file exists, creating it if it doesn't.

    Args:
        file_path: Path to the file to ensure exists.
    """
    if not os.path.exists(file_path):
        with open(file_path, 'a'):
            pass


def get_env_variable(
    var_name: str,
    default: str | None = None,
    required: bool = True,
    errors: list[str] | None = None
) -> str | None:
    """Retrieve an environment variable with validation.

    Args:
        var_name: Name of the environment variable.
        default: Default value if not found.
        required: Whether the variable is required.
        errors: List to append error messages to.

    Returns:
        The environment variable value or default.
    """
    if errors is None:
        errors = []

    value: str | None = os.getenv(var_name, default)
    if required and (value is None or value == ''):
        errors.append(f"Error: The {var_name} environment variable is required.")
    return value


# List to collect environment variable errors
env_errors: list[str] = []

# Get environment variables
SONARR_LIBRARY: str | None = get_env_variable('PLEX_ANIME_SERIES', required=False, errors=env_errors)
RADARR_LIBRARY: str | None = get_env_variable('PLEX_ANIME_MOVIES', required=False, errors=env_errors)
PLEX_URL: str | None = get_env_variable('PLEX_URL', required=True, errors=env_errors)
PLEX_TOKEN: str | None = get_env_variable('PLEX_TOKEN', required=True, errors=env_errors)
MAX_COLLECTION_SIZE: int = int(get_env_variable('MAX_COLLECTION_SIZE', default='100', required=False, errors=env_errors) or '100')
MAX_DATE_DIFF: int = int(get_env_variable('MAX_DATE_DIFF', default='4', required=False, errors=env_errors) or '4')

# Validate that at least one of SONARR_LIBRARY or RADARR_LIBRARY is provided
if not SONARR_LIBRARY and not RADARR_LIBRARY:
    env_errors.append("Error: At least one of PLEX_ANIME_SERIES or PLEX_ANIME_MOVIES environment variables is required.")

# Check for environment variable errors
if env_errors:
    for error in env_errors:
        app.logger.error(error)
    sys.exit(1)


def is_valid_url(url: str) -> bool:
    """Check if a URL is valid.

    Args:
        url: URL to validate.

    Returns:
        True if URL is valid, False otherwise.
    """
    parsed = urlparse(url)
    return all([parsed.scheme, parsed.netloc])


# Validate PLEX_URL
if PLEX_URL and not is_valid_url(PLEX_URL):
    app.logger.error(f"Error: {PLEX_URL} is not a valid URL.")
    sys.exit(1)


def connect_to_plex(url: str, token: str, max_retries: int = 6) -> PlexServer:
    """Connect to Plex server with retry logic.

    Args:
        url: Plex server URL.
        token: Plex authentication token.
        max_retries: Maximum number of connection attempts.

    Returns:
        Connected PlexServer instance.

    Raises:
        Exception: If connection fails after all retries.
    """
    retry_delay: int = 5  # seconds
    last_exception: Exception | None = None

    for attempt in range(max_retries):
        try:
            plex_server: PlexServer = PlexServer(url, token)
            app.logger.info("Successfully connected to Plex")
            return plex_server
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                app.logger.warning(f"Failed to connect to Plex server, retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff

    # If we get here, all retries failed
    app.logger.error(f"Max retries exceeded for connecting to Plex server: {str(last_exception)}")
    raise last_exception or Exception("Failed to connect to Plex server")


# Ensure PLEX_URL and PLEX_TOKEN are not None before connecting
if PLEX_URL is None or PLEX_TOKEN is None:
    app.logger.error("PLEX_URL or PLEX_TOKEN is not set")
    sys.exit(1)

plex: PlexServer = connect_to_plex(PLEX_URL, PLEX_TOKEN)
