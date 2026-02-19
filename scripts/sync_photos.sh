#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate the virtual environment and sync our photos
source "${SCRIPT_DIR}/../venv/bin/activate"
python "${SCRIPT_DIR}/sync_photos.py"
deactivate
