from __future__ import annotations

import json
import logging
import time
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image
from pillow_heif import register_heif_opener
from requests.exceptions import RequestException

# Register HEIF opener to enable reading HEIC files.
register_heif_opener()

LOGGER = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG_PATH = SCRIPT_DIR / 'config.json'
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.5
JPEG_EXTENSIONS = {'.jpg', '.jpeg'}


def validate_config(config: dict) -> None:
    """Validate required configuration keys exist and are non-empty."""
    required_keys = ['immich_server_url', 'api_key', 'album_id', 'local_folder']
    missing_keys = [key for key in required_keys if not config.get(key)]
    if missing_keys:
        raise ValueError(f"Missing required configuration keys: {', '.join(missing_keys)}")


def load_config(config_path: Path = LOCAL_CONFIG_PATH) -> dict:
    """Load JSON config from disk."""
    with config_path.open(encoding='utf-8') as config_file:
        return json.load(config_file)


def resolve_photos_path(local_folder: str) -> Path:
    """Resolve the local folder to an absolute path."""
    folder_path = Path(local_folder)
    if folder_path.is_absolute():
        return folder_path
    return (SCRIPT_DIR / folder_path).resolve()


def convert_to_jpeg(image_bytes: bytes, output_path: Path) -> None:
    """Convert image bytes to JPEG and write to output_path."""
    with Image.open(BytesIO(image_bytes)) as image:
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image.save(output_path, 'JPEG', quality=95)


def get_with_retries(
    url: str,
    headers: dict[str, str],
    timeout: int,
    retries: int = REQUEST_RETRIES,
) -> requests.Response:
    """Perform an HTTP GET with retries for transient failures."""
    last_error = None
    for attempt in range(retries):
        try:
            return requests.get(url, headers=headers, timeout=timeout)
        except RequestException as error:
            last_error = error
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF_BASE_SECONDS ** attempt)

    if last_error is not None:
        raise last_error
    raise RequestException('GET request failed without exception details')


def to_local_jpg_name(original_file_name: str) -> str:
    """Convert an asset filename to the local JPG filename format."""
    return f'{Path(original_file_name).stem}.jpg'


def sync_photos() -> None:
    """Synchronize photos from Immich album to local storage."""
    local_config = load_config()
    validate_config(local_config)

    immich_server_url = local_config['immich_server_url'].rstrip('/')
    api_key = local_config['api_key']
    album_id = local_config['album_id']
    photos_path = resolve_photos_path(local_config['local_folder'])

    headers = {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
    }

    response = get_with_retries(
        url=f'{immich_server_url}/api/albums/{album_id}',
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    album = response.json()
    photos = album.get('assets', [])

    photos_path.mkdir(parents=True, exist_ok=True)

    if not photos:
        LOGGER.info('No photos returned from Immich. Removing local photos to match empty album.')
    else:
        LOGGER.info('Found %s photos in album.', len(photos))

    downloaded_count = 0
    expected_filenames = {
        to_local_jpg_name(photo['originalFileName'])
        for photo in photos
        if 'originalFileName' in photo
    }

    for photo in photos:
        original_file_name = photo.get('originalFileName')
        asset_id = photo.get('id')

        if not original_file_name or not asset_id:
            LOGGER.warning('Skipping asset with missing fields: %s', repr(photo))
            continue

        local_filename = to_local_jpg_name(original_file_name)
        local_path = photos_path / local_filename
        if local_path.exists():
            continue

        LOGGER.info('Downloading %s...', local_filename)
        download_url = f'{immich_server_url}/api/assets/{asset_id}/original'

        try:
            download_response = get_with_retries(
                url=download_url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            download_response.raise_for_status()

            file_ext = Path(original_file_name).suffix.lower()
            if file_ext in JPEG_EXTENSIONS:
                local_path.write_bytes(download_response.content)
                LOGGER.info('Saved %s', local_filename)
            else:
                LOGGER.info('Converting %s to JPG...', original_file_name)
                convert_to_jpeg(download_response.content, local_path)
                LOGGER.info('Saved converted file %s', local_filename)

            downloaded_count += 1
        except RequestException as error:
            LOGGER.error('Error downloading %s: %s', local_filename, error)
        except Exception:
            LOGGER.exception('Error processing %s', local_filename)

    existing_files = {entry.name for entry in photos_path.iterdir() if entry.is_file()}
    for filename in sorted(existing_files - expected_filenames):
        file_path = photos_path / filename
        try:
            file_path.unlink()
            LOGGER.info('Deleted %s', filename)
        except OSError as error:
            LOGGER.error('Error deleting %s: %s', filename, error)

    LOGGER.info('Sync complete. Downloaded %s new photos.', downloaded_count)


def main() -> int:
    """Run sync as a script and return an exit code."""
    try:
        sync_photos()
        return 0
    except FileNotFoundError:
        LOGGER.error('Configuration file not found at %s', LOCAL_CONFIG_PATH)
    except json.JSONDecodeError as error:
        LOGGER.error('Invalid JSON in configuration file: %s', error)
    except ValueError as error:
        LOGGER.error('Configuration issue: %s', error)
    except RequestException as error:
        LOGGER.error('Immich request failed: %s', error)
    except Exception:
        LOGGER.exception('Unexpected error during sync')

    return 1


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    raise SystemExit(main())
