import os
import json
import requests
from datetime import datetime
from requests.exceptions import RequestException, Timeout, ConnectionError

ABSOLUTE_PATH = os.path.dirname(__file__)
LOCAL_CONFIG = os.path.join(ABSOLUTE_PATH, "config.json")

# Absolute path to the photos directory
PHOTOS_DIR = os.path.join(os.path.dirname(__file__), '..', 'photos')

# HTTP request timeout in seconds
REQUEST_TIMEOUT = 10


def validate_config(config):
    """Validate required configuration keys exist and are non-empty.

    Args:
        config: Dictionary containing configuration values.

    Raises:
        ValueError: If required configuration is missing or empty.
    """
    required_keys = ['immich_server_url', 'api_key', 'album_id', 'local_folder']
    missing_keys = [key for key in required_keys if not config.get(key)]
    if missing_keys:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing_keys)}")


def sync_photos():
    """Synchronize photos from Immich album to local storage.

    Fetches photos from the specified Immich album and downloads them to the
    configured local folder. Removes local files that no longer exist in the album.
    """
    try:
        with open(LOCAL_CONFIG) as f:
            local_config = json.load(f)

        validate_config(local_config)

        immich_server_url = local_config['immich_server_url'].rstrip('/')
        api_key = local_config['api_key']
        album_id = local_config['album_id']
        local_folder = local_config['local_folder']

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }

        # Fetch photos from Immich album with timeout
        try:
            response = requests.get(
                f"{immich_server_url}/api/albums/{album_id}",
                headers=headers,
                timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            album = response.json()
            photos = album.get('assets', [])
        except (RequestException, Timeout) as e:
            print(f"Error fetching album from Immich: {e}")
            return

        # Check if no photos are returned
        if not photos:
            print("No photos returned from Immich. Local folder remains unchanged.")
            return

        print(f"Found {len(photos)} photos.")

        # Create local photos directory if it doesn't exist
        photos_path = os.path.join(ABSOLUTE_PATH, local_folder)
        os.makedirs(photos_path, exist_ok=True)

        # Download photos
        downloaded_count = 0
        for photo in photos:
            filename = photo['originalFileName']
            asset_id = photo['id']

            # Construct download URL for original file
            download_url = f"{immich_server_url}/api/assets/{asset_id}/original"

            local_path = os.path.join(photos_path, filename)

            if not os.path.exists(local_path):
                print(f"Downloading {filename}...")
                try:
                    download_response = requests.get(
                        download_url,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT
                    )
                    if download_response.status_code == 200:
                        with open(local_path, 'wb') as file:
                            file.write(download_response.content)
                        print(f"Successfully downloaded {filename}")
                        downloaded_count += 1
                    else:
                        print(f"Failed to download {filename}: HTTP {download_response.status_code}")
                except (RequestException, Timeout) as e:
                    print(f"Error downloading {filename}: {e}")
                    continue

        # Delete photos not in the album
        existing_files = os.listdir(photos_path)
        photo_filenames = [photo['originalFileName'] for photo in photos]

        for filename in list(existing_files):  # Create copy to avoid modification during iteration
            if filename not in photo_filenames:
                file_path = os.path.join(photos_path, filename)
                try:
                    os.remove(file_path)
                    print(f"Deleted {filename}")
                except OSError as e:
                    print(f"Error deleting {filename}: {e}")

        print(f"Sync complete. Downloaded {downloaded_count} new photos.")

    except FileNotFoundError:
        print(f"Error: Configuration file not found at {LOCAL_CONFIG}")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in configuration file: {e}")
    except ValueError as e:
        print(f"Error: Configuration issue: {e}")
    except Exception as e:
        print(f"Unexpected error during sync: {e}")

if __name__ == '__main__':
    sync_photos()