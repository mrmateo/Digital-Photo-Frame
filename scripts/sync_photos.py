from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from requests.exceptions import RequestException

from photo_sync_service import (
    DEFAULT_CONFIG_PATH,
    JPEG_EXTENSIONS,
    REQUEST_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    RETRY_BACKOFF_BASE_SECONDS,
    SCRIPT_DIR,
    PhotoSyncService,
)

LOGGER = logging.getLogger(__name__)

LOCAL_CONFIG_PATH = DEFAULT_CONFIG_PATH
DEFAULT_SERVICE = PhotoSyncService(config_path=LOCAL_CONFIG_PATH, logger=LOGGER)


def validate_config(config: dict) -> None:
    """Validate required configuration keys exist and are non-empty."""
    DEFAULT_SERVICE.validate_config(config)


def load_config(config_path: Path = LOCAL_CONFIG_PATH) -> dict:
    """Load JSON config from disk."""
    return DEFAULT_SERVICE.load_config(config_path)


def resolve_photos_path(local_folder: str) -> Path:
    """Resolve the local folder to an absolute path."""
    return DEFAULT_SERVICE.resolve_photos_path(local_folder)


def convert_to_jpeg(image_bytes: bytes, output_path: Path) -> None:
    """Convert image bytes to JPEG and write to output_path."""
    DEFAULT_SERVICE.convert_to_jpeg(image_bytes, output_path)


def get_with_retries(
    url: str,
    headers: dict[str, str],
    timeout: int,
    retries: int = REQUEST_RETRIES,
):
    """Perform an HTTP GET with retries for transient failures."""
    return DEFAULT_SERVICE.get_with_retries(url=url, headers=headers, timeout=timeout, retries=retries)


def to_local_jpg_name(original_file_name: str) -> str:
    """Convert an asset filename to the local JPG filename format."""
    return DEFAULT_SERVICE.to_local_jpg_name(original_file_name)


def sync_photos(progress_callback: Callable[[str], None] | None = None) -> dict[str, int]:
    """Synchronize photos from Immich album to local storage."""
    summary = DEFAULT_SERVICE.sync_photos(progress_callback=progress_callback)
    return summary.to_dict()


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
