from flask import Flask
from plexapi.server import PlexServer
from urllib.parse import urlparse
import os, sys, logging, time

app = Flask(__name__)

# Remove Flask's default handler
for handler in app.logger.handlers:
    app.logger.removeHandler(handler)

# Set up custom logging
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
))
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)

def ensure_file_exists(file_path):
    if not os.path.exists(file_path):
        with open(file_path, 'a') as file:
            pass

def get_env_variable(var_name, default=None, required=True, errors=[]):
    value = os.getenv(var_name, default)
    if required and (value is None or value == ''):
        errors.append(f"Error: The {var_name} environment variable is required.")
    return value

# List to collect environment variable errors
env_errors = []

# Get environment variables
SONARR_LIBRARY = get_env_variable('PLEX_ANIME_SERIES', required=False, errors=env_errors)
RADARR_LIBRARY = get_env_variable('PLEX_ANIME_MOVIES', required=False, errors=env_errors)
PLEX_URL = get_env_variable('PLEX_URL', required=True, errors=env_errors)
PLEX_TOKEN = get_env_variable('PLEX_TOKEN', required=True, errors=env_errors)
MAX_COLLECTION_SIZE = int(get_env_variable('MAX_COLLECTION_SIZE', default='100', required=False, errors=env_errors))
MAX_DATE_DIFF = int(get_env_variable('MAX_DATE_DIFF', default='4', required=False, errors=env_errors))

# Validate that at least one of SONARR_LIBRARY or RADARR_LIBRARY is provided
if not SONARR_LIBRARY and not RADARR_LIBRARY:
    env_errors.append("Error: At least one of PLEX_ANIME_SERIES or PLEX_ANIME_MOVIES environment variables is required.")

# Check for environment variable errors
if env_errors:
    for error in env_errors:
        app.logger.error(error)
    sys.exit(1)

def is_valid_url(url):
    parsed = urlparse(url)
    return all([parsed.scheme, parsed.netloc])

# Validate PLEX_URL
if not is_valid_url(PLEX_URL):
    app.logger.error(f"Error: {PLEX_URL} is not a valid URL.")
    sys.exit(1)

def connect_to_plex(url, token, max_retries=5):
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            plex = PlexServer(url, token)
            return plex  # Successfully connected, return the server object
        except Exception as e:
            if attempt < max_retries - 1:
                logging.warning(f"Failed to connect to Plex server, retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                logging.error(f"Max retries exceeded for connecting to Plex server: {str(e)}")
                raise

plex = connect_to_plex(PLEX_URL, PLEX_TOKEN)