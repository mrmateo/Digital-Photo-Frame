#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."

"${PROJECT_ROOT}/venv/bin/python" -m unittest discover -s "${PROJECT_ROOT}/tests" -v
