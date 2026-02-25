#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Activate the virtual environment and display our photos
source "${SCRIPT_DIR}/../venv/bin/activate"
python "${SCRIPT_DIR}/run_photo_display.py"
deactivate
