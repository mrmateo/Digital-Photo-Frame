from datetime import datetime
import json
import logging
import os
import subprocess
import time
from threading import Thread
import requests
from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from sync_photos import sync_photos

# Setup logging
logging.basicConfig(filename='app.log', level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(message)s')


class TapImage(Image):

    def __init__(self, **kwargs):
        super(TapImage, self).__init__(**kwargs)
        self.last_touch_time = 0.0
        self.last_nav_side = None
        self.last_nav_time = 0.0
        self.touch_threshold = 0.2  # 200 milliseconds
        self.edge_threshold = 0.4  # 40% of the width from each edge
        self.opposite_side_window = 1.0

    def on_touch_down(self, touch):
        """
        Handle touch events on the left and right areas of the screen.

        Args:
            touch (TouchEvent): The touch event object.

        Returns:
            bool: True if the touch event is handled, False otherwise.
        """
        if not self.collide_point(*touch.pos):
            return super(TapImage, self).on_touch_down(touch)

        current_time = time.monotonic()
        if current_time - self.last_touch_time < self.touch_threshold:
            return True  # Debounce rapid touches

        local_x = touch.x - self.x
        side = None

        if local_x < self.width * self.edge_threshold:
            side = 'left'
        elif local_x > self.width * (1 - self.edge_threshold):
            side = 'right'

        if not side:
            return super(TapImage, self).on_touch_down(touch)

        if (
            self.last_nav_side is not None
            and side != self.last_nav_side
            and (current_time - self.last_nav_time) < self.opposite_side_window
        ):
            return True

        self.last_touch_time = current_time
        self.last_nav_side = side
        self.last_nav_time = current_time

        app = App.get_running_app()
        if app:
            if side == 'left':
                app.load_previous_image(manual=True)
            else:
                app.load_next_image(force=True, manual=True)

            return True

        return super(TapImage, self).on_touch_down(touch)


class InfoPanel(BoxLayout):

    def __init__(self, **kwargs):
        super(InfoPanel, self).__init__(**kwargs)
        with self.canvas.before:
            Color(0.04, 0.06, 0.10, 0.45)
            self._panel_bg = RoundedRectangle(radius=[dp(18)])

        self.bind(pos=self._update_panel_bg, size=self._update_panel_bg)

    def _update_panel_bg(self, *_):
        self._panel_bg.pos = self.pos
        self._panel_bg.size = self.size


class PhotoFrameApp(App):

    def build(self):
        """Setup our Kivy app and return the root widget.

        Raises:
            Exception: If no images are found in the photos directory.

        Returns:
            Root widget of the Kivy app.
        """

        self.image_cache = {}  # Cache of images and their last modified time
        self.local_config = self.load_config()  # Load our local configuration
        self.apply_settings()  # Configure Kivy with defined settings
        self.index = 0
        self.sync_in_progress = False
        self.weather_request_in_progress = False
        self.photos_path = self.resolve_photos_path(self.local_config.get('local_folder'))
        os.makedirs(self.photos_path, exist_ok=True)
        self.images = self.load_images(self.photos_path)
        self.toast = None

        if not self.images:
            logging.warning("No images found in the directory.")
            return FloatLayout()  # Return an empty layout to avoid crashing

        self.image_widget = TapImage(source=self.images[self.index],
                                     fit_mode="cover", opacity=1)

        layout = FloatLayout()

        layout.add_widget(self.image_widget)
        self.image_cycle_seconds = 15
        self.image_cycle_event = Clock.schedule_interval(self.update_image, self.image_cycle_seconds)

        # Schedule the check for new images every hour (3600 seconds)
        Clock.schedule_interval(self.check_for_new_images, 3600)

        # Build our information panel (time, date, weather)
        self.info_panel = InfoPanel(
            orientation='vertical',
            size_hint=(None, None),
            size=(dp(360), dp(150)),
            pos_hint={'x': 0.04, 'y': 0.02},
            padding=(dp(16), dp(12), dp(16), dp(12)),
            spacing=dp(4)
        )
        self.weather_icons_dir = os.path.join(os.path.dirname(__file__), 'assets', 'weather')

        self.clock_label = Label(
            text=self.get_current_time(),
            font_size='50sp',
            color=[1, 1, 1, 1],
            bold=True,
            size_hint=(1, None),
            height=dp(68),
            halign='left',
            valign='middle'
        )
        self.clock_label.bind(size=self._sync_text_size)

        self.date_label = Label(
            text=self.get_current_date(),
            font_size='18sp',
            color=[0.86, 0.90, 0.96, 1],
            size_hint=(1, None),
            height=dp(28),
            halign='left',
            valign='middle'
        )
        self.date_label.bind(size=self._sync_text_size)

        self.weather_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None),
            height=dp(40),
            spacing=dp(10)
        )

        self.weather_icon = Image(
            source=self.get_weather_icon_path(None),
            size_hint=(None, None),
            size=(dp(30), dp(30)),
            fit_mode='contain',
            pos_hint={'center_y': 0.5}
        )

        self.weather_label = Label(
            text='Weather loading...',
            font_size='24sp',
            color=[0.95, 0.99, 1, 1],
            size_hint=(1, None),
            height=dp(40),
            halign='left',
            valign='middle'
        )
        self.weather_label.bind(size=self._sync_text_size)

        button_path = os.path.join(os.path.dirname(__file__), 'assets')
        refresh_icon = os.path.join(button_path, 'refresh_icon.png')
        power_icon = os.path.join(button_path, 'power_icon.png')

        self.weather_controls = BoxLayout(
            orientation='horizontal',
            size_hint=(None, None),
            size=(dp(116), dp(44)),
            spacing=dp(8),
            pos_hint={'center_y': 0.5}
        )

        self.refresh_button = Button(
            background_normal=refresh_icon,
            background_down=refresh_icon,
            border=(0, 0, 0, 0),
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            opacity=1
        )
        self.refresh_button.bind(on_press=self.check_for_new_images)

        self.power_button = Button(
            background_normal=power_icon,
            background_down=power_icon,
            border=(0, 0, 0, 0),
            size_hint=(None, None),
            size=(dp(44), dp(44)),
            opacity=1
        )
        self.power_button.bind(on_press=self.power_off)

        self.weather_controls.add_widget(self.refresh_button)
        self.weather_controls.add_widget(self.power_button)

        self.weather_row.add_widget(self.weather_icon)
        self.weather_row.add_widget(self.weather_label)
        self.weather_row.add_widget(self.weather_controls)

        self.info_panel.add_widget(self.clock_label)
        self.info_panel.add_widget(self.date_label)
        self.info_panel.add_widget(self.weather_row)
        layout.add_widget(self.info_panel)

        self.update_info_panel_layout()
        Window.bind(size=self.on_window_resize)

        Clock.schedule_interval(self.update_clock, 1)  # Update clock every second
        Clock.schedule_interval(self.update_weather, 3600)  # Update weather every hour
        Clock.schedule_once(self.update_weather, 0)  # Load weather asynchronously

        return layout

    def show_toast(self, message):
        if not self.toast:
            self.toast = Label(size_hint=(None, None), font_size='20sp',
                               bold=True, pos_hint={'center_x': 0.5, 'center_y': 0.1})
            App.get_running_app().root.add_widget(self.toast)

        self.toast.text = message
        self.toast.opacity = 1  # Make sure it's visible

        anim = Animation(opacity=0, duration=5)
        anim.bind(on_complete=lambda *x: setattr(self.toast, 'opacity', 0))
        anim.start(self.toast)

    def load_config(self):
        # Get the path to our config file
        config_path = os.path.join(os.path.dirname(__file__), 'config.json')

        with open(config_path) as config_file:
            config = json.load(config_file)

        return config

    def resolve_photos_path(self, local_folder):
        default_path = os.path.join(os.path.dirname(__file__), '../photos')
        if not local_folder:
            return os.path.normpath(default_path)

        if os.path.isabs(local_folder):
            return local_folder

        return os.path.normpath(os.path.join(os.path.dirname(__file__), local_folder))

    def _sync_text_size(self, label, _size):
        label.text_size = (label.width, label.height)

    def on_window_resize(self, *_):
        self.update_info_panel_layout()

    def update_info_panel_layout(self):
        is_portrait = Window.height >= Window.width

        if is_portrait:
            panel_width = max(dp(360), min(dp(660), Window.width * 0.88))
            panel_height = dp(205)
            self.info_panel.pos_hint = {'center_x': 0.5, 'y': 0.03}
            self.info_panel.padding = (dp(20), dp(14), dp(20), dp(14))
            self.info_panel.spacing = dp(8)
            self.clock_label.font_size = '64sp'
            self.date_label.font_size = '24sp'
            self.weather_label.font_size = '28sp'
            self.clock_label.height = dp(86)
            self.date_label.height = dp(34)
            self.weather_row.height = dp(64)
            self.weather_label.height = dp(64)
            self.weather_icon.size = (dp(40), dp(40))
            self.weather_controls.size = (dp(132), dp(52))
            self.refresh_button.size = (dp(52), dp(52))
            self.power_button.size = (dp(52), dp(52))
        else:
            panel_width = max(dp(280), min(dp(460), Window.width * 0.56))
            panel_height = dp(160)
            self.info_panel.pos_hint = {'x': 0.04, 'y': 0.02}
            self.info_panel.padding = (dp(16), dp(12), dp(16), dp(12))
            self.info_panel.spacing = dp(4)
            self.clock_label.font_size = '50sp'
            self.date_label.font_size = '18sp'
            self.weather_label.font_size = '24sp'
            self.clock_label.height = dp(68)
            self.date_label.height = dp(28)
            self.weather_row.height = dp(50)
            self.weather_label.height = dp(50)
            self.weather_icon.size = (dp(34), dp(34))
            self.weather_controls.size = (dp(112), dp(44))
            self.refresh_button.size = (dp(44), dp(44))
            self.power_button.size = (dp(44), dp(44))

        self.info_panel.size = (panel_width, panel_height)

    def apply_settings(self):
        """
        Configure Kivy to run in borderless fullscreen mode.
        """
        Config.set('graphics', 'fullscreen', 'auto')
        Config.set('graphics', 'borderless', True)
        Config.write()

        Window.show_cursor = False

    def power_off(self, instance):
        """
        Safely shut down the Raspberry Pi.
        """
        logging.info("Shutting down...")
        try:
            subprocess.run(['sudo', 'shutdown', 'now'], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logging.error("Error while trying to power off: %s", e)
            self.show_toast("Failed to power off.")

    def resolve_weather_icon_key(self, condition: str | None) -> str:
        """Map weather condition to a weather icon key."""
        condition_lower = condition.lower() if condition else ''

        icon_keys = {
            'sunny': 'sun',
            'clear': 'sun',
            'cloudy': 'cloud',
            'partlycloudy': 'partly_cloudy',
            'mostlycloudy': 'cloud',
            'overcast': 'cloud',
            'rain': 'rain',
            'lightrain': 'rain',
            'heavyrain': 'heavy_rain',
            'showers': 'rain',
            'drizzle': 'rain',
            'thunderstorm': 'storm',
            'thunder': 'storm',
            'snow': 'snow',
            'lightsnow': 'snow',
            'heavysnow': 'snow',
            'blizzard': 'snow',
            'fog': 'fog',
            'haze': 'fog',
            'windy': 'wind',
            'rainandsnow': 'mix',
        }

        if condition_lower in icon_keys:
            return icon_keys[condition_lower]

        for key, icon_key in icon_keys.items():
            if key in condition_lower:
                return icon_key

        return 'unknown'

    def get_weather_icon_path(self, condition: str | None) -> str:
        icon_key = self.resolve_weather_icon_key(condition)
        icon_path = os.path.join(self.weather_icons_dir, f'{icon_key}.png')

        if os.path.exists(icon_path):
            return icon_path

        return os.path.join(self.weather_icons_dir, 'unknown.png')

    def format_weather_condition(self, condition: str) -> str:
        """Format Home Assistant condition strings for display."""
        if not condition:
            return 'Unknown'

        normalized = condition.lower().replace('-', '').replace('_', '')
        friendly_names = {
            'partlycloudy': 'Partly Cloudy',
            'mostlycloudy': 'Mostly Cloudy',
            'lightrain': 'Light Rain',
            'heavyrain': 'Heavy Rain',
            'thunderstorm': 'Thunderstorm',
            'lightsnow': 'Light Snow',
            'heavysnow': 'Heavy Snow',
            'rainandsnow': 'Rain and Snow',
        }

        if normalized in friendly_names:
            return friendly_names[normalized]

        return condition.replace('_', ' ').replace('-', ' ').title()

    def fetch_weather_data(self) -> tuple[str, str]:
        """
        Fetch weather data from local Home Assistant instance.

        Returns:
            tuple[str, str]: Weather text and weather icon path.
        """
        api_key = self.local_config.get('weather_api_key')
        url = self.local_config.get('home_assistant_weather_url')

        if not api_key or not url:
            logging.warning("Weather config missing weather_api_key or home_assistant_weather_url")
            return "Weather unavailable", self.get_weather_icon_path(None)

        retries = 3
        timeout = 8
        last_error = None

        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=timeout
                )
                response.raise_for_status()
                data = response.json()

                temperature = round(data['attributes']['temperature'])
                condition = data['state']
                weather = self.format_weather_condition(condition)
                weather_icon_path = self.get_weather_icon_path(condition)

                return f"{temperature} F  |  {weather}", weather_icon_path
            except requests.RequestException as e:
                last_error = e
                if attempt < retries - 1:
                    time.sleep(1.5 ** attempt)
            except (KeyError, TypeError, ValueError) as e:
                logging.error("Unexpected weather payload: %s", e)
                return "Weather unavailable", self.get_weather_icon_path(None)

        logging.error("Error fetching weather data: %s", last_error)
        return "Weather unavailable", self.get_weather_icon_path(None)

    def get_current_time(self):
        current_time = datetime.now()
        formatted_time = current_time.strftime('%I:%M %p')
        return formatted_time

    def get_current_date(self):
        current_date = datetime.now()
        return current_date.strftime('%A, %b %d')

    def update_clock(self, dt):
        self.clock_label.text = self.get_current_time()
        self.date_label.text = self.get_current_date()

    def update_weather(self, dt=None):
        if self.weather_request_in_progress:
            return

        self.weather_request_in_progress = True
        Thread(target=self._update_weather_worker, daemon=True).start()

    def _update_weather_worker(self):
        try:
            weather_text, icon_path = self.fetch_weather_data()
        except Exception as e:
            logging.error("Unhandled error while fetching weather data: %s", e)
            weather_text = "Weather unavailable"
            icon_path = self.get_weather_icon_path(None)
        Clock.schedule_once(lambda dt: self._apply_weather_update(weather_text, icon_path), 0)

    def _apply_weather_update(self, weather_text, icon_path):
        self.weather_label.text = weather_text
        if self.weather_icon.source != icon_path:
            self.weather_icon.source = icon_path
            self.weather_icon.reload()
        self.weather_request_in_progress = False

    def check_for_new_images(self, dt=None):
        """
        Check for new images in the photos directory and reload the images if new images are found.
        """
        if self.sync_in_progress:
            return

        self.sync_in_progress = True
        Thread(target=self._sync_images_worker, daemon=True).start()

    def _sync_images_worker(self):
        sync_error = None
        try:
            sync_photos()
        except Exception as e:
            logging.error("Error syncing photos: %s", e)
            sync_error = e

        Clock.schedule_once(lambda dt: self._apply_synced_images(sync_error), 0)

    def _apply_synced_images(self, sync_error=None):
        self.sync_in_progress = False

        if sync_error:
            self.show_toast("Error syncing photos.")
            return

        new_images = self.load_images(self.photos_path)

        if new_images != self.images:
            self.show_toast("Images updated. Reloading...")
            self.images = new_images

            if not self.images:
                logging.warning("No images found in the photos directory.")
                return

            # If the currently displayed image was deleted, load the first image from the new list
            if self.image_widget.source not in self.images:
                self.index = 0
                self.image_widget.source = self.images[self.index]

            self.load_next_image(force=True)  # Force refresh the displayed image
        else:
            self.show_toast("No new images found.")

    def update_image(self, dt=None):
        """
        Update the image being displayed on the slideshow timer.
        """
        if not self.images:
            return

        self.load_next_image(force=True)

    def reset_image_cycle_timer(self):
        if self.image_cycle_event is not None:
            self.image_cycle_event.cancel()
        self.image_cycle_event = Clock.schedule_interval(self.update_image, self.image_cycle_seconds)

    def prepare_manual_navigation(self):
        Animation.cancel_all(self.image_widget)
        self.image_widget.opacity = 1
        self.reset_image_cycle_timer()

    def load_next_image(self, force=False, manual=False):
        """
        Load the next image in the list and fade it in.
        """
        if not self.images:
            return

        if not (manual or force):
            return

        if manual:
            self.prepare_manual_navigation()

        self.index = (self.index + 1) % len(self.images)
        self.image_widget.source = self.images[self.index]

        if manual:
            self.image_widget.opacity = 1
            return

        Animation.cancel_all(self.image_widget)
        self.image_widget.opacity = 0
        anim = Animation(opacity=1, duration=1.5)
        anim.start(self.image_widget)

    def load_previous_image(self, manual=False):
        """
        Load the previous image in the list and fade it in.
        """
        if not self.images:
            return

        if manual:
            self.prepare_manual_navigation()

        self.index = (self.index - 1) % len(self.images)
        self.image_widget.source = self.images[self.index]

        if manual:
            self.image_widget.opacity = 1
            return

        Animation.cancel_all(self.image_widget)
        self.image_widget.opacity = 0
        anim = Animation(opacity=1, duration=1.5)
        anim.start(self.image_widget)

    def load_images(self, path: str):
        """
        Load all images in the given path.

        Args:
            path (str): Path to our photos directory.

        Returns:
            List: List of images in our photos directory.
        """
        images = []
        for file in sorted(os.scandir(path), key=lambda entry: entry.name.lower()):
            if file.is_file() and file.name.lower().endswith(('.jpg', '.jpeg', '.png')):
                full_path = os.path.join(path, file.name)
                mod_time = os.path.getmtime(full_path)

                # Update the cache for new or modified files
                if full_path not in self.image_cache or self.image_cache[full_path] < mod_time:
                    self.image_cache[full_path] = mod_time

                images.append(full_path)

        # Remove entries for images that are no longer present
        for cached_path in list(self.image_cache.keys()):
            if cached_path not in images:
                del self.image_cache[cached_path]

        return images


if __name__ == '__main__':
    PhotoFrameApp().run()
