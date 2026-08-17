#!/usr/bin/env bash
# Build the PyInstaller bundle and pack module.tar.gz.
# Run by Viam cloud build (meta.json build.build).
set -euo pipefail

cd "$(dirname "$0")"

VENV=./.venv/bin
[ -x "$VENV/python" ] || { echo "run ./setup.sh first" >&2; exit 1; }
[ -f models/gesture_recognizer.task ] || { echo "model missing; run ./setup.sh" >&2; exit 1; }

echo "==> tests"
"$VENV/python" -m pytest tests/ -q

echo "==> pyinstaller (onedir)"
rm -rf build dist
"$VENV/python" -m PyInstaller --clean --noconfirm main.spec

echo "==> packing module.tar.gz"
# dist/main/ is the whole onedir bundle: the launcher plus _internal/.
tar -czf module.tar.gz meta.json dist/main

echo "==> built $(du -h module.tar.gz | cut -f1) for ${VIAM_BUILD_OS:-$(uname)}/${VIAM_BUILD_ARCH:-$(uname -m)}"
