import os
import json
import time
import requests
from requests.exceptions import RequestException, Timeout
from pathlib import Path
from io import BytesIO
from PIL import Image
from pillow_heif import register_heif_opener

# Register HEIF opener to enable reading HEIC files
register_heif_opener()

ABSOLUTE_PATH = os.path.dirname(__file__)
LOCAL_CONFIG = os.path.join(ABSOLUTE_PATH, "config.json")

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


def resolve_photos_path(local_folder):
    """Resolve local folder to an absolute path.

    Relative paths are resolved from the scripts directory.
    """
    if os.path.isabs(local_folder):
        return local_folder
    return os.path.normpath(os.path.join(ABSOLUTE_PATH, local_folder))


def convert_to_jpeg(image_bytes, output_path):
    """Convert image bytes to JPEG and save to output_path."""
    with Image.open(BytesIO(image_bytes)) as image:
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(output_path, 'JPEG', quality=95)


def get_with_retries(url, headers, timeout, retries=3):
    """Perform an HTTP GET with retry support for transient failures."""
    last_error = None
    for attempt in range(retries):
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except (RequestException, Timeout) as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(1.5 ** attempt)

    if last_error is not None:
        raise last_error

    raise RequestException("GET request failed without exception details")


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
            response = get_with_retries(
                url=f"{immich_server_url}/api/albums/{album_id}",
                headers=headers,
                timeout=REQUEST_TIMEOUT,
                retries=3
            )
            response.raise_for_status()
            album = response.json()
            photos = album.get('assets', [])
        except (RequestException, Timeout) as e:
            print(f"Error fetching album from Immich: {e}")
            return

        # Create local photos directory if it doesn't exist
        photos_path = resolve_photos_path(local_folder)
        os.makedirs(photos_path, exist_ok=True)

        if not photos:
            print("No photos returned from Immich. Removing local photos to match empty album.")
        else:
            print(f"Found {len(photos)} photos.")

        # Download photos
        downloaded_count = 0
        for photo in photos:
            filename = photo['originalFileName']
            asset_id = photo['id']

            # Use original endpoint to download the file
            download_url = f"{immich_server_url}/api/assets/{asset_id}/original"

            # Change extension to jpg if it's not already
            filename_jpg = Path(filename).stem + '.jpg'
            local_path = os.path.join(photos_path, filename_jpg)

            if not os.path.exists(local_path):
                print(f"Downloading {filename_jpg}...")
                try:
                    download_response = get_with_retries(
                        url=download_url,
                        headers=headers,
                        timeout=REQUEST_TIMEOUT,
                        retries=3
                    )
                    download_response.raise_for_status()

                    file_ext = Path(filename).suffix.lower()
                    if file_ext in ['.jpg', '.jpeg']:
                        with open(local_path, 'wb') as file:
                            file.write(download_response.content)
                        print(f"Successfully downloaded {filename_jpg}")
                    else:
                        print(f"Converting {filename} to JPG...")
                        convert_to_jpeg(download_response.content, local_path)
                        print(f"Successfully converted and saved {filename_jpg}")

                    downloaded_count += 1
                except (RequestException, Timeout) as e:
                    print(f"Error downloading {filename_jpg}: {e}")
                    continue
                except Exception as e:
                    print(f"Error processing {filename_jpg}: {e}")
                    continue

        # Delete photos not in the album
        existing_files = [
            filename for filename in os.listdir(photos_path)
            if os.path.isfile(os.path.join(photos_path, filename))
        ]
        # Use the converted JPG filenames for comparison
        photo_filenames = [Path(photo['originalFileName']).stem + '.jpg' for photo in photos]

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
