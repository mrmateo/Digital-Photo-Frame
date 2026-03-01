from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        app.refresh_button = type('ButtonState', (), {'disabled': False, 'opacity': 1})()
        app.sync_status_label = type('StatusLabel', (), {'text': '', 'opacity': 0})()
        app.sync_status_panel = type('StatusPanel', (), {'opacity': 0})()
        app.sync_status_clear_event = None
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

    def test_power_off_runs_shutdown_command(self) -> None:
        app = self.make_app()
        app.show_toast = Mock()

        with patch('run_photo_display.subprocess.run') as mock_run:
            app.power_off(None)

        mock_run.assert_called_once_with(['sudo', 'shutdown', 'now'], check=True)
        app.show_toast.assert_not_called()

    def test_power_off_shows_toast_when_shutdown_fails(self) -> None:
        app = self.make_app()
        app.show_toast = Mock()

        with patch(
            'run_photo_display.subprocess.run',
            side_effect=subprocess.CalledProcessError(returncode=1, cmd=['sudo', 'shutdown', 'now']),
        ):
            app.power_off(None)

        app.show_toast.assert_called_once_with('Failed to power off.')

    def test_power_off_shows_toast_when_sudo_missing(self) -> None:
        app = self.make_app()
        app.show_toast = Mock()

        with patch('run_photo_display.subprocess.run', side_effect=FileNotFoundError('sudo not found')):
            app.power_off(None)

        app.show_toast.assert_called_once_with('Failed to power off.')

    def test_apply_settings_sets_fullscreen_and_hides_cursor(self) -> None:
        app = self.make_app()
        fake_window = SimpleNamespace(show_cursor=True)

        with (
            patch('run_photo_display.Config.set') as mock_config_set,
            patch('run_photo_display.Config.write') as mock_config_write,
            patch('run_photo_display.Window', fake_window),
        ):
            app.apply_settings()

        mock_config_set.assert_any_call('graphics', 'fullscreen', 'auto')
        mock_config_set.assert_any_call('graphics', 'borderless', True)
        mock_config_write.assert_called_once()
        self.assertFalse(fake_window.show_cursor)

    def test_apply_synced_images_shows_error_toast_when_sync_fails(self) -> None:
        app = self.make_app()
        app.sync_in_progress = True
        app.refresh_button.disabled = True
        app.show_toast = Mock()
        app.load_images = Mock()

        app._apply_synced_images(sync_error=RuntimeError('sync failed'))

        self.assertFalse(app.sync_in_progress)
        self.assertFalse(app.refresh_button.disabled)
        app.show_toast.assert_called_once_with('Error syncing photos.')
        app.load_images.assert_not_called()
        self.assertIn('Sync failed', app.sync_status_label.text)

    def test_apply_synced_images_resets_when_current_image_removed(self) -> None:
        app = self.make_app()
        app.sync_in_progress = True
        app.images = ['old.jpg']
        app.image_widget = type('Widget', (), {'source': 'old.jpg', 'opacity': 0})()
        app.index = 0
        app.photos_path = '/unused'
        app.show_toast = Mock()
        app.load_images = Mock(return_value=['new1.jpg', 'new2.jpg'])

        summary = {'downloaded': 2, 'deleted': 1, 'converted': 1, 'failed': 0}

        app._apply_synced_images(sync_summary=summary)

        self.assertFalse(app.sync_in_progress)
        app.show_toast.assert_not_called()
        self.assertEqual(app.index, 0)
        self.assertEqual(app.image_widget.source, 'new1.jpg')
        self.assertEqual(app.image_widget.opacity, 1)
        self.assertEqual(app.sync_status_label.text, 'Sync complete: 2 added, 1 removed, 1 converted.')

    def test_apply_synced_images_reports_no_changes(self) -> None:
        app = self.make_app()
        app.sync_in_progress = True
        app.images = ['one.jpg']
        app.image_widget = type('Widget', (), {'source': 'one.jpg', 'opacity': 1})()
        app.photos_path = '/unused'
        app.show_toast = Mock()
        app.load_images = Mock(return_value=['one.jpg'])

        app._apply_synced_images(sync_summary={'downloaded': 0, 'deleted': 0, 'converted': 0, 'failed': 0})

        self.assertFalse(app.sync_in_progress)
        app.show_toast.assert_not_called()
        self.assertEqual(app.sync_status_label.text, 'Sync complete: no changes.')

    def test_apply_synced_images_keeps_current_image_when_still_present(self) -> None:
        app = self.make_app()
        app.sync_in_progress = True
        app.images = ['one.jpg']
        app.image_widget = type('Widget', (), {'source': 'one.jpg', 'opacity': 0})()
        app.index = 0
        app.photos_path = '/unused'
        app.show_toast = Mock()
        app.load_images = Mock(return_value=['one.jpg', 'two.jpg'])
        app.load_next_image = Mock()

        app._apply_synced_images(sync_summary={'downloaded': 1, 'deleted': 0, 'converted': 0, 'failed': 0})

        app.show_toast.assert_not_called()
        app.load_next_image.assert_not_called()
        self.assertEqual(app.image_widget.source, 'one.jpg')
        self.assertEqual(app.index, 0)
        self.assertEqual(app.image_widget.opacity, 1)

    def test_format_sync_summary_reports_changes(self) -> None:
        app = self.make_app()

        message = app.format_sync_summary({'downloaded': 5, 'deleted': 2, 'converted': 1, 'failed': 0})

        self.assertEqual(message, 'Sync complete: 5 added, 2 removed, 1 converted.')

    def test_format_sync_summary_reports_no_changes(self) -> None:
        app = self.make_app()

        message = app.format_sync_summary({'downloaded': 0, 'deleted': 0, 'converted': 0, 'failed': 0})

        self.assertEqual(message, 'Sync complete: no changes.')

    def test_check_for_new_images_disables_button_and_sets_status(self) -> None:
        app = self.make_app()
        app.sync_in_progress = False

        with patch('run_photo_display.Thread') as mock_thread:
            app.check_for_new_images()

        self.assertTrue(app.sync_in_progress)
        self.assertTrue(app.refresh_button.disabled)
        self.assertEqual(app.refresh_button.opacity, 0.45)
        self.assertEqual(app.sync_status_label.text, 'Syncing photos...')
        mock_thread.assert_called_once()

    def test_check_for_new_images_ignores_duplicate_requests_while_syncing(self) -> None:
        app = self.make_app()
        app.sync_in_progress = True

        with patch('run_photo_display.Thread') as mock_thread:
            app.check_for_new_images()

        mock_thread.assert_not_called()
        self.assertIn('already in progress', app.sync_status_label.text)


class TapImageInteractionTests(unittest.TestCase):
    def make_touch(self, x_value: float):
        return SimpleNamespace(x=x_value, pos=(x_value, 10))

    def make_app(self):
        return SimpleNamespace(
            load_previous_image=Mock(),
            load_next_image=Mock(),
        )

    def test_left_tap_loads_previous_image(self) -> None:
        image = run_photo_display.TapImage()
        image.x = 0
        image.width = 100
        touch = self.make_touch(10)
        fake_app = self.make_app()

        with (
            patch.object(image, 'collide_point', return_value=True),
            patch('run_photo_display.App.get_running_app', return_value=fake_app),
            patch('run_photo_display.time.monotonic', return_value=1.0),
        ):
            handled = image.on_touch_down(touch)

        self.assertTrue(handled)
        fake_app.load_previous_image.assert_called_once_with(manual=True)
        fake_app.load_next_image.assert_not_called()

    def test_right_tap_loads_next_image(self) -> None:
        image = run_photo_display.TapImage()
        image.x = 0
        image.width = 100
        touch = self.make_touch(90)
        fake_app = self.make_app()

        with (
            patch.object(image, 'collide_point', return_value=True),
            patch('run_photo_display.App.get_running_app', return_value=fake_app),
            patch('run_photo_display.time.monotonic', return_value=1.0),
        ):
            handled = image.on_touch_down(touch)

        self.assertTrue(handled)
        fake_app.load_next_image.assert_called_once_with(manual=True)
        fake_app.load_previous_image.assert_not_called()

    def test_debounce_prevents_rapid_repeat_navigation(self) -> None:
        image = run_photo_display.TapImage()
        image.x = 0
        image.width = 100
        fake_app = self.make_app()
        touch = self.make_touch(10)

        with (
            patch.object(image, 'collide_point', return_value=True),
            patch('run_photo_display.App.get_running_app', return_value=fake_app),
            patch('run_photo_display.time.monotonic', side_effect=[1.0, 1.1]),
        ):
            image.on_touch_down(touch)
            image.on_touch_down(touch)

        fake_app.load_previous_image.assert_called_once_with(manual=True)

    def test_opposite_side_tap_is_ignored_inside_block_window(self) -> None:
        image = run_photo_display.TapImage()
        image.x = 0
        image.width = 100
        left_touch = self.make_touch(10)
        right_touch = self.make_touch(90)
        fake_app = self.make_app()

        with (
            patch.object(image, 'collide_point', return_value=True),
            patch('run_photo_display.App.get_running_app', return_value=fake_app),
            patch('run_photo_display.time.monotonic', side_effect=[1.0, 1.5]),
        ):
            image.on_touch_down(left_touch)
            image.on_touch_down(right_touch)

        fake_app.load_previous_image.assert_called_once_with(manual=True)
        fake_app.load_next_image.assert_not_called()


class UiLayoutContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.patches = []

        load_config_patch = patch.object(
            run_photo_display.PhotoFrameApp,
            'load_config',
            return_value={'local_folder': self.temp_dir.name},
        )
        self.mock_load_config = load_config_patch.start()
        self.patches.append(load_config_patch)

        apply_settings_patch = patch.object(run_photo_display.PhotoFrameApp, 'apply_settings', return_value=None)
        self.mock_apply_settings = apply_settings_patch.start()
        self.patches.append(apply_settings_patch)

        check_images_patch = patch.object(run_photo_display.PhotoFrameApp, 'check_for_new_images', return_value=None)
        self.mock_check_for_new_images = check_images_patch.start()
        self.patches.append(check_images_patch)

        update_weather_patch = patch.object(run_photo_display.PhotoFrameApp, 'update_weather', return_value=None)
        self.mock_update_weather = update_weather_patch.start()
        self.patches.append(update_weather_patch)

        self.app = run_photo_display.PhotoFrameApp()
        self.root = self.app.build()
        self.app.root = self.root

    def tearDown(self) -> None:
        if getattr(self.app, 'image_cycle_event', None) is not None:
            self.app.image_cycle_event.cancel()

        run_photo_display.Clock.unschedule(self.app.update_image)
        run_photo_display.Clock.unschedule(self.app.update_clock)
        run_photo_display.Clock.unschedule(self.app.check_for_new_images)
        run_photo_display.Clock.unschedule(self.app.update_weather)
        run_photo_display.Window.unbind(size=self.app.on_window_resize)

        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def normalize(value: float) -> float:
        return value / run_photo_display.dp(1)

    @staticmethod
    def _rect(widget) -> tuple[float, float, float, float]:
        return (widget.x, widget.y, widget.right, widget.top)

    def _apply_layout(self, width_dp: float, height_dp: float) -> None:
        scale = run_photo_display.dp(1)
        fake_window = SimpleNamespace(width=width_dp * scale, height=height_dp * scale)
        with patch('run_photo_display.Window', fake_window):
            self.app.update_info_panel_layout()

        self.root.size = (fake_window.width, fake_window.height)
        self.root.pos = (0, 0)
        self.root.do_layout()
        self.app.sync_status_panel.do_layout()
        self.app.info_panel.do_layout()
        self.app.weather_row.do_layout()
        run_photo_display.Clock.tick()

    def _assert_inside_panel(self, child, label: str) -> None:
        panel_left, panel_bottom, panel_right, panel_top = self._rect(self.app.info_panel)
        child_left, child_bottom, child_right, child_top = self._rect(child)
        epsilon = 0.5

        self.assertGreaterEqual(child_left + epsilon, panel_left, f'{label} left edge is outside panel')
        self.assertGreaterEqual(child_bottom + epsilon, panel_bottom, f'{label} bottom edge is outside panel')
        self.assertLessEqual(child_right - epsilon, panel_right, f'{label} right edge is outside panel')
        self.assertLessEqual(child_top - epsilon, panel_top, f'{label} top edge is outside panel')

    def test_landscape_layout_contract(self) -> None:
        self._apply_layout(width_dp=1280, height_dp=720)

        self.assertAlmostEqual(self.normalize(self.app.info_panel.size[0]), 560, delta=0.5)
        self.assertAlmostEqual(self.normalize(self.app.info_panel.size[1]), 206, delta=1.0)
        self.assertAlmostEqual(self.normalize(self.app.clock_label.font_size), 54, delta=0.5)
        self.assertAlmostEqual(self.normalize(self.app.weather_label.font_size), 26, delta=0.5)
        self.assertAlmostEqual(self.normalize(self.app.weather_controls.size[0]), 172, delta=0.5)
        self.assertEqual(self.app.info_panel.pos_hint, {'x': 0.04, 'y': 0.02})
        self.assertGreater(self.app.sync_status_panel.y, self.app.info_panel.top)

    def test_portrait_layout_contract(self) -> None:
        self._apply_layout(width_dp=720, height_dp=1280)

        self.assertAlmostEqual(self.normalize(self.app.info_panel.size[0]), 662.4, delta=0.8)
        self.assertAlmostEqual(self.normalize(self.app.info_panel.size[1]), 252, delta=1.0)
        self.assertAlmostEqual(self.normalize(self.app.clock_label.font_size), 68, delta=0.5)
        self.assertAlmostEqual(self.normalize(self.app.weather_label.font_size), 30, delta=0.5)
        self.assertAlmostEqual(self.normalize(self.app.weather_controls.size[0]), 196, delta=0.5)
        self.assertEqual(self.app.info_panel.pos_hint, {'center_x': 0.5, 'y': 0.03})
        self.assertGreater(self.app.sync_status_panel.y, self.app.info_panel.top)

    def test_info_panel_visual_style_contract(self) -> None:
        self.assertEqual(self.app.clock_label.color, [1, 1, 1, 1])
        self.assertEqual(self.app.date_label.color, [0.86, 0.9, 0.96, 1])
        self.assertEqual(self.app.weather_label.color, [0.95, 0.99, 1, 1])
        self.assertEqual(self.app.weather_label.text, 'Weather loading...')
        self.assertEqual(self.app.sync_status_label.text, '')
        self.assertEqual(self.app.sync_status_label.opacity, 0)
        self.assertEqual(self.app.sync_status_panel.opacity, 0)

    def test_landscape_widgets_stay_inside_translucent_panel(self) -> None:
        self._apply_layout(width_dp=1280, height_dp=720)

        self._assert_inside_panel(self.app.clock_label, 'clock_label')
        self._assert_inside_panel(self.app.date_label, 'date_label')
        self._assert_inside_panel(self.app.weather_row, 'weather_row')
        self._assert_inside_panel(self.app.weather_label, 'weather_label')
        self._assert_inside_panel(self.app.weather_icon, 'weather_icon')
        self._assert_inside_panel(self.app.weather_controls, 'weather_controls')

    def test_portrait_widgets_stay_inside_translucent_panel(self) -> None:
        self._apply_layout(width_dp=720, height_dp=1280)

        self._assert_inside_panel(self.app.clock_label, 'clock_label')
        self._assert_inside_panel(self.app.date_label, 'date_label')
        self._assert_inside_panel(self.app.weather_row, 'weather_row')
        self._assert_inside_panel(self.app.weather_label, 'weather_label')
        self._assert_inside_panel(self.app.weather_icon, 'weather_icon')
        self._assert_inside_panel(self.app.weather_controls, 'weather_controls')

    def test_power_button_press_triggers_shutdown_command(self) -> None:
        with patch('run_photo_display.subprocess.run') as mock_run:
            self.app.power_button.dispatch('on_press')

        mock_run.assert_called_once_with(['sudo', 'shutdown', 'now'], check=True)

    def test_refresh_button_press_triggers_sync_callback(self) -> None:
        before = self.mock_check_for_new_images.call_count
        self.app.refresh_button.dispatch('on_press')
        after = self.mock_check_for_new_images.call_count
        self.assertEqual(after, before + 1)


if __name__ == '__main__':
    unittest.main()
