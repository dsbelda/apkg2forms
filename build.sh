#!/bin/sh
# Genera un ejecutable autónomo en dist/ (macOS: apkg2forms.app, Linux: apkg2forms). Hay que ejecutarlo en cada sistema.
set -e
cd "$(dirname "$0")"
python3 -m venv .buildenv
.buildenv/bin/pip install -q pyinstaller zstandard pypdf pillow
.buildenv/bin/pyinstaller --noconfirm --windowed --onefile apkg2forms.py
rm -rf .buildenv build apkg2forms.spec
