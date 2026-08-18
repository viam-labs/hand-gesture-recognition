#!/usr/bin/env bash
# Runs once on the target machine when the module is installed.
#
# libmediapipe.so links against GL/GLES/EGL, and OpenCV needs glib. PyInstaller
# deliberately refuses to bundle the GL family — they have to match the host's
# graphics drivers — so they must come from the system. Without them the module
# dies on import with "libGLESv2.so.2: cannot open shared object file".
#
# macOS needs nothing: the .dylib has no such dependency.
#
# This does NOT create a Python environment. The module ships as a
# self-contained PyInstaller bundle, so there is no venv to build.
set -euo pipefail

[ "$(uname)" = "Linux" ] || exit 0

REQUIRED_LIBS="libGLESv2.so.2 libEGL.so.1 libglib-2.0.so.0"

find_missing() {
    local out=""
    for lib in $REQUIRED_LIBS; do
        ldconfig -p 2>/dev/null | grep -q -- "$lib" || out="$out $lib"
    done
    printf '%s' "$out"
}

MISSING=$(find_missing)
if [ -z "$MISSING" ]; then
    echo "==> required system libraries already present"
    exit 0
fi
echo "==> missing system libraries:$MISSING"

if ! command -v apt-get >/dev/null 2>&1; then
    cat >&2 <<MSG
ERROR: missing system libraries and apt-get is unavailable on this machine.

Install the equivalents of these packages with your distribution's package
manager, then restart the module:

  libglib2.0-0  libgl1  libegl1  libgles2

They provide:$MISSING
MSG
    exit 1
fi

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || {
        echo "ERROR: not root and sudo is unavailable; cannot install:$MISSING" >&2
        exit 1
    }
    SUDO="sudo"
fi

echo "==> installing system libraries"
$SUDO apt-get -qq update
$SUDO apt-get -qq install -y libglib2.0-0 libgl1 libegl1
# libgles2 is named libgles2-mesa on Ubuntu 22.04 and older.
$SUDO apt-get -qq install -y libgles2 || $SUDO apt-get -qq install -y libgles2-mesa

STILL_MISSING=$(find_missing)
if [ -n "$STILL_MISSING" ]; then
    echo "ERROR: still missing after install:$STILL_MISSING" >&2
    exit 1
fi
echo "==> system libraries installed"
