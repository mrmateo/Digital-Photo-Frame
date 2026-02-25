from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from requests.exceptions import RequestException

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / 'scripts' / 'config.json'
REQUEST_TIMEOUT_SECONDS = 10


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Load JSON config from disk."""
    with config_path.open(encoding='utf-8') as config_file:
        return json.load(config_file)


def check_immich_album_api(config: dict) -> None:
    """Call the Immich album endpoint and print a short result."""
    url = f"{config['immich_server_url']}/api/albums/{config['album_id']}"
    headers = {
        'x-api-key': config['api_key'],
        'Content-Type': 'application/json',
    }

    print('Testing connection to Immich API...')
    print(f"URL: {config['immich_server_url']}")
    print(f"Album ID: {config['album_id']}")

    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    print(f'Status Code: {response.status_code}')
    response.raise_for_status()

    album = response.json()
    photos = album.get('assets', [])
    print(f"Success! Found {len(photos)} photos in the configured album.")

    if photos:
        sample = photos[0]
        print('\nSample photo:')
        print(f"  ID: {sample.get('id', 'N/A')}")
        print(f"  Filename: {sample.get('originalFileName', 'N/A')}")
        print(f"  Created: {sample.get('localDateTime', 'N/A')}")


def main() -> int:
    """Run the API connectivity check script and return an exit code."""
    try:
        config = load_config()
        required_keys = ['immich_server_url', 'album_id', 'api_key']
        missing_keys = [key for key in required_keys if not config.get(key)]
        if missing_keys:
            print(f"Missing required config keys: {', '.join(missing_keys)}")
            return 1

        check_immich_album_api(config)
        return 0
    except FileNotFoundError:
        print(f'Config file not found: {CONFIG_PATH}')
    except json.JSONDecodeError as error:
        print(f'Invalid JSON in config file: {error}')
    except RequestException as error:
        print(f'Request failed: {error}')
    except Exception as error:
        print(f'Error: {error}')

    return 1


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RequestException(f'HTTP {self.status_code}')


class ApiScriptTests(unittest.TestCase):
    def test_load_config_reads_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / 'config.json'
            config_path.write_text(
                json.dumps({'immich_server_url': 'http://immich', 'album_id': 'abc', 'api_key': 'key'}),
                encoding='utf-8',
            )

            loaded = load_config(config_path)

        self.assertEqual(loaded['album_id'], 'abc')

    def test_main_returns_one_when_required_keys_are_missing(self) -> None:
        with (
            patch('test_api.load_config', return_value={'immich_server_url': 'http://immich'}),
            patch('builtins.print'),
        ):
            result = main()

        self.assertEqual(result, 1)

    def test_main_returns_zero_on_successful_api_call(self) -> None:
        config = {
            'immich_server_url': 'http://immich',
            'album_id': 'album-1',
            'api_key': 'key-1',
        }
        response = FakeResponse(json_data={'assets': [{'id': '1', 'originalFileName': 'photo.jpg'}]})

        with (
            patch('test_api.load_config', return_value=config),
            patch('test_api.requests.get', return_value=response) as mock_get,
            patch('builtins.print'),
        ):
            result = main()

        self.assertEqual(result, 0)
        mock_get.assert_called_once()

    def test_main_returns_one_when_request_fails(self) -> None:
        config = {
            'immich_server_url': 'http://immich',
            'album_id': 'album-1',
            'api_key': 'key-1',
        }

        with (
            patch('test_api.load_config', return_value=config),
            patch('test_api.requests.get', side_effect=RequestException('network down')),
            patch('builtins.print'),
        ):
            result = main()

        self.assertEqual(result, 1)


if __name__ == '__main__':
    raise SystemExit(main())
