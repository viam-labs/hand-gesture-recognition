#!/usr/bin/env bash
# Create the build virtualenv and vendor the gesture model.
# Run by Viam cloud build (meta.json build.setup) and usable locally.
set -euo pipefail

cd "$(dirname "$0")"

MODEL_URL="https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
MODEL_PATH="models/gesture_recognizer.task"

# The MediaPipe wheel ships no model files, so the .task bundle must be fetched
# and vendored into the tarball — the module must not depend on network at runtime.
if [ ! -f "$MODEL_PATH" ]; then
  echo "==> downloading gesture model"
  mkdir -p models
  curl -fsSL -o "$MODEL_PATH" "$MODEL_URL"
fi
echo "==> model present: $MODEL_PATH ($(du -h "$MODEL_PATH" | cut -f1))"

UNAME=$(uname)
if [ "$UNAME" = "Linux" ]; then
  # libmediapipe.so links against GL/GLES/EGL and opencv needs glib, none of
  # which are present on a minimal Linux install or a CI runner. Without these
  # every import fails with "libGLESv2.so.2: cannot open shared object file".
  echo "==> installing system libraries"
  SUDO=""
  [ "$(id -u)" -ne 0 ] && SUDO="sudo"
  $SUDO apt-get -qq update
  $SUDO apt-get -qq install -y python3-venv python3-dev libglib2.0-0 libgl1 libegl1
  # libgles2 is named libgles2-mesa on Ubuntu 22.04 and older.
  $SUDO apt-get -qq install -y libgles2 || $SUDO apt-get -qq install -y libgles2-mesa
elif [ "$UNAME" = "Darwin" ]; then
  command -v python3 >/dev/null 2>&1 || { echo "python3 not found; install it first" >&2; exit 1; }
  ARCH=$(uname -m)
  if [ "$ARCH" != "arm64" ]; then
    echo "ERROR: MediaPipe publishes no macOS x86_64 wheel — Apple Silicon is required." >&2
    exit 1
  fi
else
  echo "ERROR: unsupported OS '$UNAME'" >&2
  exit 1
fi

echo "==> creating venv"
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt
./.venv/bin/pip install pyinstaller pytest

echo "==> setup complete"
