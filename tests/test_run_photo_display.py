from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

os.environ.setdefault('KIVY_NO_ARGS', '1')

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_photo_display  # noqa: E402


class FakeResponse:
    def __init__(self, *, json_data=None, status_code: int = 200):
        self._json_data = json_data if json_data is not None else {}
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}')


class FakeAnimation:
    cancelled_widgets = []
    started = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @staticmethod
    def cancel_all(widget) -> None:
        FakeAnimation.cancelled_widgets.append(widget)

    def start(self, widget) -> None:
        FakeAnimation.started.append((widget, self.kwargs))


class RunPhotoDisplayTests(unittest.TestCase):
    def make_app(self) -> run_photo_display.PhotoFrameApp:
        app = run_photo_display.PhotoFrameApp.__new__(run_photo_display.PhotoFrameApp)
        app.local_config = {}
        app.weather_icons_dir = ''
        app.images = []
        app.index = 0
        app.image_widget = type('Widget', (), {'source': '', 'opacity': 1})()
        return app

    def test_resolve_weather_icon_key_handles_exact_partial_and_unknown(self) -> None:
        app = self.make_app()

        self.assertEqual(app.resolve_weather_icon_key('mostlycloudy'), 'cloud')
        self.assertEqual(app.resolve_weather_icon_key('tonight-cloudy-skies'), 'cloud')
        self.assertEqual(app.resolve_weather_icon_key('totally-new-condition'), 'unknown')

    def test_format_weather_condition_formats_known_and_generic_values(self) -> None:
        app = self.make_app()

        self.assertEqual(app.format_weather_condition('partly_cloudy'), 'Partly Cloudy')
        self.assertEqual(app.format_weather_condition('clear-night'), 'Clear Night')

    def test_resolve_photos_path_supports_default_absolute_and_relative(self) -> None:
        app = self.make_app()

        default_path = app.resolve_photos_path(None)
        self.assertTrue(default_path.endswith('photos'))

        absolute = '/tmp/frame-path'
        self.assertEqual(app.resolve_photos_path(absolute), absolute)

        relative = app.resolve_photos_path('my-photos')
        expected = os.path.normpath(os.path.join(os.path.dirname(run_photo_display.__file__), 'my-photos'))
        self.assertEqual(relative, expected)

    def test_load_images_returns_sorted_supported_files(self) -> None:
        app = self.make_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            photo_dir = Path(temp_dir)
            (photo_dir / 'B.JPG').write_bytes(b'jpg')
            (photo_dir / 'a.png').write_bytes(b'png')
            (photo_dir / 'notes.txt').write_text('ignore me', encoding='utf-8')

            images = app.load_images(str(photo_dir))

        self.assertEqual([Path(path).name for path in images], ['a.png', 'B.JPG'])

    def test_fetch_weather_data_returns_unavailable_when_not_configured(self) -> None:
        app = self.make_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            weather_dir = Path(temp_dir)
            (weather_dir / 'unknown.png').write_bytes(b'unknown')

            app.local_config = {}
            app.weather_icons_dir = str(weather_dir)

            text, icon_path = app.fetch_weather_data()

        self.assertEqual(text, 'Weather unavailable')
        self.assertTrue(icon_path.endswith('unknown.png'))

    def test_fetch_weather_data_retries_then_succeeds(self) -> None:
        app = self.make_app()

        with tempfile.TemporaryDirectory() as temp_dir:
            weather_dir = Path(temp_dir)
            (weather_dir / 'rain.png').write_bytes(b'rain')
            (weather_dir / 'unknown.png').write_bytes(b'unknown')

            app.weather_icons_dir = str(weather_dir)
            app.local_config = {
                'weather_api_key': 'token',
                'home_assistant_weather_url': 'http://home-assistant.local/weather',
            }

            payload = {'attributes': {'temperature': 71.7}, 'state': 'light_rain'}
            with (
                patch(
                    'run_photo_display.requests.get',
                    side_effect=[requests.RequestException('temporary'), FakeResponse(json_data=payload)],
                ) as mock_get,
                patch('run_photo_display.time.sleep') as mock_sleep,
            ):
                text, icon_path = app.fetch_weather_data()

        self.assertIn('72 F', text)
        self.assertIn('Light Rain', text)
        self.assertEqual(icon_path, str(weather_dir / 'rain.png'))
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once()

    def test_load_next_image_manual_mode_changes_image_without_animation(self) -> None:
        app = self.make_app()
        app.images = ['one.jpg', 'two.jpg']
        app.index = 0
        app.image_widget.source = 'one.jpg'
        app.prepare_manual_navigation = Mock()

        app.load_next_image(manual=True)

        app.prepare_manual_navigation.assert_called_once()
        self.assertEqual(app.index, 1)
        self.assertEqual(app.image_widget.source, 'two.jpg')
        self.assertEqual(app.image_widget.opacity, 1)

    def test_load_next_image_auto_mode_uses_animation(self) -> None:
        app = self.make_app()
        app.images = ['one.jpg', 'two.jpg']
        app.index = 0
        app.image_widget.source = 'one.jpg'
        FakeAnimation.cancelled_widgets = []
        FakeAnimation.started = []

        with patch('run_photo_display.Animation', FakeAnimation):
            app.load_next_image(manual=False)

        self.assertEqual(app.index, 1)
        self.assertEqual(app.image_widget.source, 'two.jpg')
        self.assertEqual(app.image_widget.opacity, 0)
        self.assertEqual(len(FakeAnimation.cancelled_widgets), 1)
        self.assertEqual(len(FakeAnimation.started), 1)

    def test_load_previous_image_manual_mode_changes_image(self) -> None:
        app = self.make_app()
        app.images = ['one.jpg', 'two.jpg']
        app.index = 1
        app.image_widget.source = 'two.jpg'
        app.prepare_manual_navigation = Mock()

        app.load_previous_image(manual=True)

        app.prepare_manual_navigation.assert_called_once()
        self.assertEqual(app.index, 0)
        self.assertEqual(app.image_widget.source, 'one.jpg')


if __name__ == '__main__':
    unittest.main()
