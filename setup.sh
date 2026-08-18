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
  # Bounded and retried: a stalled connection here has no natural timeout and
  # would hang the build (or a machine's first run) indefinitely.
  curl -fsSL --connect-timeout 20 --max-time 300 --retry 3 --retry-delay 5 \
    -o "$MODEL_PATH" "$MODEL_URL"
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

  # apt has two ways to wait forever with no output: debconf asking a question,
  # and needrestart asking which services to restart (the default on Ubuntu
  # 22.04+, and a known way to wedge CI runners). Silence both, and cap each
  # call so a stall fails loudly instead of hanging.
  export DEBIAN_FRONTEND=noninteractive
  export NEEDRESTART_MODE=a
  export NEEDRESTART_SUSPEND=1

  apt_get() {
    if command -v timeout >/dev/null 2>&1; then
      timeout 600 $SUDO apt-get -qq \
        -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
    else
      $SUDO apt-get -qq \
        -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"
    fi
  }

  apt_get update
  apt_get install -y python3-venv python3-dev libglib2.0-0 libgl1 libegl1
  # libgles2 is named libgles2-mesa on Ubuntu 22.04 and older.
  apt_get install -y libgles2 || apt_get install -y libgles2-mesa
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

# pip has no default socket timeout either, so a stalled PyPI connection hangs
# forever. These downloads are large (mediapipe, opencv, matplotlib), which makes
# a stall more likely, not less.
export PIP_DEFAULT_TIMEOUT=60
PIP_ARGS="--retries 5"
./.venv/bin/pip install $PIP_ARGS --upgrade pip
./.venv/bin/pip install $PIP_ARGS -r requirements.txt
./.venv/bin/pip install $PIP_ARGS pyinstaller pytest

echo "==> setup complete"
