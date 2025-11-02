# Plex Dubbed Episodes Updater Docker Container

## Environment Variables

| **Variable**            | **Required**  | **Default** | **Description**                                                                         | **Example**            |
|-------------------------|---------------|-------------|-----------------------------------------------------------------------------------------|------------------------|
| `PORT`                  | ❌            | `5000`      | The port the container will listen on                                                   | `5000`                 |
| `PLEX_URL`              | ✅            |             | URL of your Plex server                                                                 | `http://plex:32400`    |
| `PLEX_TOKEN`            | ✅            |             | Your Plex server token                                                                  | `YourPlexToken`        |
| `PLEX_ANIME_SERIES`     | ⚠️            |             | Plex library name for anime series (Sonarr).                                            | `Anime Series`         |
| `PLEX_ANIME_MOVIES`     | ⚠️            |             | Plex library name for anime movies (Radarr).                                            | `Anime Movies`         |
| `MAX_COLLECTION_SIZE`   | ❌            | `100`       | Max number of episodes/movies in the collection                                         | `100`                  |
| `MAX_DATE_DIFF`         | ❌            | `4`         | Max days difference for considering recent releases                                     | `4`                    |

> ✅ = Required  
> ❌ = Optional  
> ⚠️ = Check Notes  
> Note: Either `PLEX_ANIME_SERIES` or `PLEX_ANIME_MOVIES` must be provided, but it's not mandatory to provide both.  
> Note: `MAX_DATE_DIFF` is useful for those anime that release dubbed episodes at the same time that subbed episodes come out.

## Requirements

### Tags

- **Purpose:** I use them to identify anime series and movies.
- **Why:** The container looks for english tracks reported from sonarr, so sending all series to the container would result in false positives. Tags are used to filter out non-anime series and movies.

## How it Works

### Download Actions

- **Trigger**: Occurs when an episode or movie is downloaded.
- **Conditions**:
  - The media must be dubbed.
  - It is either an upgrade or a recent release (as determined by `MAX_DATE_DIFF`).
  - The media ID is not already in the deque (to avoid re-adding to collection in the case of upgrades).
- **Action**:
  - If all conditions are met, the media is added to the collection.
  - This ensures that only relevant, upgraded, or newly released dubbed media is included.

### Deletion Actions

- **Trigger**: Occurs when an episode or movie is deleted for an upgrade.
- **Condition**: Checks if the deleted media contained an English track.
- **Action**: Adds the media ID to a deque. This prevents re-adding the same media when the upgraded version is downloaded.

## Usage

1. Set the environment variables in your Docker configuration.
2. Deploy the Docker container.
3. Configure Sonarr and Radarr to send webhooks to the container.

This container listens for webhooks from Sonarr and Radarr, and when it receives notification of an episode or movie upgrade, it checks if the media is dubbed. If dubbed, it updates the specified Plex collection with the latest media.

## Sonarr Settings

![image](https://github.com/Heavybullets8/new-plex-dubs/assets/20793231/3847d1ca-e902-4567-9877-63a835aeb31a)

> `http://URL:PORT/sonarr`

## Radarr Settings

![image](https://github.com/Heavybullets8/new-plex-dubs/assets/20793231/11aa2328-438b-47bd-bafd-4a634d373f64)

> `http://URL:PORT/radarr`

## Warning

I made this purely for personal use, but published it in the event anyone else found it useful. I likely will not offer any type of support.

