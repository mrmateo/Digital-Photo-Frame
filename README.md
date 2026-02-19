# Digital Photo Frame

![SonarCloud Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=tyler-tee_Digital-Photo-Frame&metric=alert_status)


## Overview
Kivy-based application developed to run on a raspberry pi. Designed to display photos synced from an Immich server on a touchscreen display. Created for Christmas 2023 as a gift for my ~~fiance~~ wife and father.

## Key Features
- **Photo Synchronization**: Integrates with Immich API to sync photos.
- **Interactive UI**: Navigate through photos with touch gestures.
- **Weather and Time Display**: Fetches and shows current weather and time.
- **Automatic Updates**: Periodically syncs new photos and deletes old ones.

## Initial Setup
1. **Install Python**: Ensure Python >=3.9 is installed on your Raspberry Pi.
2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure API and Local Settings**:
    - Create a `config.json` with keys like `immich_server_url`, `api_key`, `album_id`, and `local_folder`.
    - `local_folder` may be an absolute path, or a path relative to the `scripts` directory.
    - Get your Immich API key from your Immich server settings.
      - [Get started w/ Immich](https://immich.app/docs/install/docker-compose#environment-variables)

## Running the Application
1. **Initial Photo Population**:
    - Run `sync_photos.py` initially to populate your local folder with photos from the specified Immich album.
    ```bash
    python scripts/sync_photos.py
    ```
2. **Start the Photo Display**:
    - After the initial setup, use `run_photo_display.py` to handle photo synchronization and display.
    ```bash
    python scripts/run_photo_display.py
    ```

## Notes
- The application requires an Immich server with an API key and album ID configured in `config.json`.
- For new installations, ensure your Immich server is running and accessible from the Raspberry Pi.

## Run as a Service
- A sample `.service` file is provided in `/services` for configuring the app to run with `systemctl`.

## License
This project is licensed under the MIT License.
