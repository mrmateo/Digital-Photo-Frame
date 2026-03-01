from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

import requests
from PIL import Image
from pillow_heif import register_heif_opener
from requests.exceptions import RequestException

# Register HEIF opener to enable reading HEIC files.
register_heif_opener()

LOGGER = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / 'config.json'
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_RETRIES = 3
RETRY_BACKOFF_BASE_SECONDS = 1.5
JPEG_EXTENSIONS = {'.jpg', '.jpeg'}


@dataclass
class SyncSummary:
    remote_assets: int = 0
    downloaded: int = 0
    converted: int = 0
    deleted: int = 0
    skipped_existing: int = 0
    skipped_invalid: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            'remote_assets': self.remote_assets,
            'downloaded': self.downloaded,
            'converted': self.converted,
            'deleted': self.deleted,
            'skipped_existing': self.skipped_existing,
            'skipped_invalid': self.skipped_invalid,
            'failed': self.failed,
        }


class PhotoSyncService:
    """Service responsible for syncing Immich album assets locally."""

    def __init__(
        self,
        config_path: Path = DEFAULT_CONFIG_PATH,
        logger: logging.Logger | None = None,
        request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
        request_retries: int = REQUEST_RETRIES,
        retry_backoff_base_seconds: float = RETRY_BACKOFF_BASE_SECONDS,
    ) -> None:
        self.config_path = config_path
        self.logger = logger or LOGGER
        self.request_timeout_seconds = request_timeout_seconds
        self.request_retries = request_retries
        self.retry_backoff_base_seconds = retry_backoff_base_seconds

    def _notify(self, progress_callback: Callable[[str], None] | None, message: str) -> None:
        self.logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    def validate_config(self, config: dict) -> None:
        required_keys = ['immich_server_url', 'api_key', 'album_id', 'local_folder']
        missing_keys = [key for key in required_keys if not config.get(key)]
        if missing_keys:
            raise ValueError(f"Missing required configuration keys: {', '.join(missing_keys)}")

    def load_config(self, config_path: Path | None = None) -> dict:
        path = config_path or self.config_path
        with path.open(encoding='utf-8') as config_file:
            return json.load(config_file)

    @staticmethod
    def resolve_photos_path(local_folder: str) -> Path:
        folder_path = Path(local_folder)
        if folder_path.is_absolute():
            return folder_path
        return (SCRIPT_DIR / folder_path).resolve()

    @staticmethod
    def convert_to_jpeg(image_bytes: bytes, output_path: Path) -> None:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.mode != 'RGB':
                image = image.convert('RGB')
            image.save(output_path, 'JPEG', quality=95)

    def get_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        timeout: int,
        retries: int | None = None,
    ) -> requests.Response:
        retry_count = self.request_retries if retries is None else retries

        last_error = None
        for attempt in range(retry_count):
            try:
                return requests.get(url, headers=headers, timeout=timeout)
            except RequestException as error:
                last_error = error
                if attempt < retry_count - 1:
                    time.sleep(self.retry_backoff_base_seconds ** attempt)

        if last_error is not None:
            raise last_error
        raise RequestException('GET request failed without exception details')

    @staticmethod
    def to_local_jpg_name(original_file_name: str) -> str:
        return f'{Path(original_file_name).stem}.jpg'

    def sync_photos(self, progress_callback: Callable[[str], None] | None = None) -> SyncSummary:
        local_config = self.load_config()
        self.validate_config(local_config)

        immich_server_url = local_config['immich_server_url'].rstrip('/')
        api_key = local_config['api_key']
        album_id = local_config['album_id']
        photos_path = self.resolve_photos_path(local_config['local_folder'])

        headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
        }

        self._notify(progress_callback, 'Connecting to Immich...')

        response = self.get_with_retries(
            url=f'{immich_server_url}/api/albums/{album_id}',
            headers=headers,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        album = response.json()
        photos = album.get('assets', [])

        photos_path.mkdir(parents=True, exist_ok=True)

        if not photos:
            self._notify(progress_callback, 'Album is empty. Cleaning local folder...')
        else:
            self._notify(progress_callback, f'Found {len(photos)} photos in album.')

        summary = SyncSummary(remote_assets=len(photos))

        expected_filenames = {
            self.to_local_jpg_name(photo['originalFileName'])
            for photo in photos
            if 'originalFileName' in photo
        }

        for photo in photos:
            original_file_name = photo.get('originalFileName')
            asset_id = photo.get('id')

            if not original_file_name or not asset_id:
                self.logger.warning('Skipping asset with missing fields: %s', repr(photo))
                summary.skipped_invalid += 1
                continue

            local_filename = self.to_local_jpg_name(original_file_name)
            local_path = photos_path / local_filename
            if local_path.exists():
                summary.skipped_existing += 1
                continue

            self._notify(progress_callback, f'Downloading {local_filename}...')
            download_url = f'{immich_server_url}/api/assets/{asset_id}/original'

            try:
                download_response = self.get_with_retries(
                    url=download_url,
                    headers=headers,
                    timeout=self.request_timeout_seconds,
                )
                download_response.raise_for_status()

                file_ext = Path(original_file_name).suffix.lower()
                if file_ext in JPEG_EXTENSIONS:
                    local_path.write_bytes(download_response.content)
                else:
                    self._notify(progress_callback, f'Converting {original_file_name} to JPG...')
                    self.convert_to_jpeg(download_response.content, local_path)
                    summary.converted += 1

                summary.downloaded += 1
            except RequestException as error:
                self.logger.error('Error downloading %s: %s', local_filename, error)
                summary.failed += 1
            except Exception:
                self.logger.exception('Error processing %s', local_filename)
                summary.failed += 1

        existing_files = {entry.name for entry in photos_path.iterdir() if entry.is_file()}
        for filename in sorted(existing_files - expected_filenames):
            file_path = photos_path / filename
            try:
                file_path.unlink()
                summary.deleted += 1
                self._notify(progress_callback, f'Removed {filename}')
            except OSError as error:
                self.logger.error('Error deleting %s: %s', filename, error)
                summary.failed += 1

        self.logger.info('Sync complete. Summary: %s', summary.to_dict())
        return summary
