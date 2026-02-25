from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sync_photos  # noqa: E402


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None, content: bytes = b'', text: str = ''):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.content = content
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}: {self.text}')


class SyncPhotosTests(unittest.TestCase):
    def test_validate_config_raises_for_missing_keys(self) -> None:
        with self.assertRaises(ValueError):
            sync_photos.validate_config({'immich_server_url': 'http://example'})

    def test_resolve_photos_path_handles_absolute_and_relative(self) -> None:
        absolute_path = '/tmp/frame-photos'
        self.assertEqual(sync_photos.resolve_photos_path(absolute_path), Path(absolute_path))

        relative = sync_photos.resolve_photos_path('photos')
        self.assertEqual(relative, (sync_photos.SCRIPT_DIR / 'photos').resolve())

    def test_get_with_retries_retries_then_succeeds(self) -> None:
        responses = [
            requests.RequestException('temporary error'),
            FakeResponse(status_code=200, json_data={'ok': True}),
        ]

        with (
            patch('sync_photos.requests.get', side_effect=responses) as mock_get,
            patch('sync_photos.time.sleep') as mock_sleep,
        ):
            response = sync_photos.get_with_retries('http://example.test', {}, timeout=5, retries=2)

        self.assertIsInstance(response, FakeResponse)
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    def test_sync_photos_downloads_converts_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            photos_dir = Path(temp_dir)
            stale_file = photos_dir / 'stale.jpg'
            stale_file.write_bytes(b'old')

            config = {
                'immich_server_url': 'http://immich.local:2283',
                'api_key': 'test-key',
                'album_id': 'album-1',
                'local_folder': str(photos_dir),
            }

            album_response = FakeResponse(
                json_data={
                    'assets': [
                        {'id': 'asset-1', 'originalFileName': 'family.jpg'},
                        {'id': 'asset-2', 'originalFileName': 'vacation.heic'},
                    ]
                }
            )
            jpg_response = FakeResponse(content=b'jpg-bytes')
            heic_response = FakeResponse(content=b'heic-bytes')

            def fake_convert(_image_bytes: bytes, output_path: Path) -> None:
                output_path.write_bytes(b'converted-jpg-bytes')

            with (
                patch.object(sync_photos, 'load_config', return_value=config),
                patch.object(
                    sync_photos,
                    'get_with_retries',
                    side_effect=[album_response, jpg_response, heic_response],
                ),
                patch.object(sync_photos, 'convert_to_jpeg', side_effect=fake_convert),
            ):
                sync_photos.sync_photos()

            self.assertEqual((photos_dir / 'family.jpg').read_bytes(), b'jpg-bytes')
            self.assertEqual((photos_dir / 'vacation.jpg').read_bytes(), b'converted-jpg-bytes')
            self.assertFalse(stale_file.exists())

    def test_sync_photos_skips_download_when_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            photos_dir = Path(temp_dir)
            existing = photos_dir / 'already_here.jpg'
            existing.write_bytes(b'existing')

            config = {
                'immich_server_url': 'http://immich.local:2283',
                'api_key': 'test-key',
                'album_id': 'album-1',
                'local_folder': str(photos_dir),
            }
            album_response = FakeResponse(
                json_data={'assets': [{'id': 'asset-1', 'originalFileName': 'already_here.jpg'}]}
            )

            with (
                patch.object(sync_photos, 'load_config', return_value=config),
                patch.object(sync_photos, 'get_with_retries', return_value=album_response) as mock_get,
            ):
                sync_photos.sync_photos()

            mock_get.assert_called_once()
            self.assertEqual(existing.read_bytes(), b'existing')

    def test_sync_photos_skips_assets_with_missing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            photos_dir = Path(temp_dir)
            config = {
                'immich_server_url': 'http://immich.local:2283',
                'api_key': 'test-key',
                'album_id': 'album-1',
                'local_folder': str(photos_dir),
            }
            album_response = FakeResponse(
                json_data={
                    'assets': [
                        {'id': 'asset-1'},
                        {'originalFileName': 'missing-id.jpg'},
                        {'id': 'asset-2', 'originalFileName': 'valid.jpg'},
                    ]
                }
            )
            valid_download = FakeResponse(content=b'valid-bytes')

            with (
                patch.object(sync_photos, 'load_config', return_value=config),
                patch.object(
                    sync_photos,
                    'get_with_retries',
                    side_effect=[album_response, valid_download],
                ) as mock_get,
            ):
                sync_photos.sync_photos()

            self.assertEqual((photos_dir / 'valid.jpg').read_bytes(), b'valid-bytes')
            self.assertFalse((photos_dir / 'missing-id.jpg').exists())
            self.assertEqual(mock_get.call_count, 2)

    def test_main_returns_non_zero_for_config_errors(self) -> None:
        with patch.object(sync_photos, 'sync_photos', side_effect=ValueError('bad config')):
            self.assertEqual(sync_photos.main(), 1)

    def test_main_returns_zero_when_sync_succeeds(self) -> None:
        with patch.object(sync_photos, 'sync_photos', return_value=None):
            self.assertEqual(sync_photos.main(), 0)


if __name__ == '__main__':
    unittest.main()
