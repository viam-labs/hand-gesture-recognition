#!/usr/bin/env bash
# Runs once on the target machine when the module is installed.
#
# PyInstaller deliberately refuses to bundle the GL family — those libraries have
# to match the host's graphics drivers — so they must come from the system.
# Verified against the built linux/amd64 bundle by reading DT_NEEDED across all
# 218 bundled binaries; three entries are unsatisfied at import time:
#
#   libGLESv2.so.2, libEGL.so.1   <- mediapipe/tasks/c/libmediapipe.so
#   libGL.so.1                    <- cv2.abi3.so -> libQt5Gui -> libGL
#
# The cv2 chain is not optional: cv2.abi3.so has a hard DT_NEEDED on libQt5Gui,
# and mediapipe imports cv2 eagerly. Without these the module dies on import
# with "libGLESv2.so.2: cannot open shared object file".
#
# Deliberately NOT installed: libglib is already bundled, and libxcb/libICE/libSM
# are only reached through Qt's xcb *platform plugin*, which never loads because
# nothing here opens a GUI window.
#
# macOS needs nothing: the .dylib has no such dependency.
#
# This does NOT create a Python environment. The module ships as a
# self-contained PyInstaller bundle, so there is no venv to build.
set -euo pipefail

[ "$(uname)" = "Linux" ] || exit 0

REQUIRED_LIBS="libGLESv2.so.2 libEGL.so.1 libGL.so.1"

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

  libgl1  libegl1  libgles2

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
$SUDO apt-get -qq install -y libgl1 libegl1
# libgles2 is named libgles2-mesa on Ubuntu 22.04 and older.
$SUDO apt-get -qq install -y libgles2 || $SUDO apt-get -qq install -y libgles2-mesa

STILL_MISSING=$(find_missing)
if [ -n "$STILL_MISSING" ]; then
    echo "ERROR: still missing after install:$STILL_MISSING" >&2
    exit 1
fi
echo "==> system libraries installed"
