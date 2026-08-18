"""Native-runtime housekeeping: log levels and matplotlib's cache.

Two problems, both caused by libraries we do not control but do ship.

**MediaPipe logs to stderr, and viam-server classifies all module stderr as
ERROR.** Roughly eight lines land at ERROR on every reconfigure — GL version,
XNNPACK delegate, feedback-manager warnings — so a perfectly healthy module
reads as broken, and genuine errors do not stand out. None of the usual
switches help: GLOG_minloglevel, GLOG_stderrthreshold, ABSL_MIN_LOG_LEVEL,
ABSL_STDERRTHRESHOLD and TF_CPP_MIN_LOG_LEVEL were all measured to change
nothing, because the writes come from C++ straight to file descriptor 2 and
never pass through Python.

So rather than silencing it, :func:`relay_native_stderr` captures fd 2 and
re-emits each line through the Python logger at the level its own prefix
declares. Nothing is lost and the levels become truthful.

**Matplotlib builds a font cache on first import**, which takes ~20 s and is
what makes the first reconfigure look like a hang. We never use matplotlib —
MediaPipe imports it eagerly and it cannot be excluded — so the goal is only to
make that cost predictable: pin the cache somewhere persistent and writable
instead of depending on whatever HOME viam-server happens to run with.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

#: absl/glog emit "I0000 00:00:1787068812.615497 8507068 file.cc:257] message".
#: TFLite emits bare "INFO: ...". Both are matched here.
_ABSL_PREFIX = re.compile(r"^([IWEF])\d{4}\s")
_PLAIN_PREFIX = re.compile(r"^(INFO|WARNING|ERROR|FATAL)\s*:", re.IGNORECASE)

_LEVELS = {
    "I": logging.INFO,
    "W": logging.WARNING,
    "E": logging.ERROR,
    "F": logging.CRITICAL,
}


def level_for(line: str) -> int:
    """Classify one line of native-library stderr.

    Unrecognized output is INFO rather than ERROR: these libraries are chatty
    and default-to-error is precisely the behavior being fixed. A real failure
    still carries its own E/F prefix.
    """
    m = _ABSL_PREFIX.match(line)
    if m:
        return _LEVELS[m.group(1)]
    m = _PLAIN_PREFIX.match(line)
    if m:
        return _LEVELS[m.group(1)[0].upper()]
    return logging.INFO


class NativeStderrRelay:
    """Redirects fd 2 into the logger, leaving Python's own stderr alone.

    ``sys.stderr`` is rebound to the original descriptor before the swap, so
    Python tracebacks and any logging handler that writes to stderr keep going
    to the real one. Without that, a relayed line could be logged, written back
    to stderr, recaptured, and loop forever.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or LOGGER
        self._saved_fd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self.active = False

    def start(self) -> bool:
        """Begin relaying. Returns False and changes nothing if it cannot."""
        if self.active:
            return True
        try:
            read_fd, write_fd = os.pipe()
            self._saved_fd = os.dup(2)
            # Python writes bypass the pipe -> no feedback loop.
            sys.stderr = os.fdopen(os.dup(self._saved_fd), "w", buffering=1)
            os.dup2(write_fd, 2)
            os.close(write_fd)
        except Exception:
            self._logger.debug("could not relay native stderr", exc_info=True)
            self._restore()
            return False

        self._thread = threading.Thread(
            target=self._pump, args=(read_fd,), name="native-stderr-relay", daemon=True
        )
        self._thread.start()
        self.active = True
        return True

    def _pump(self, read_fd: int) -> None:
        try:
            with os.fdopen(read_fd, "r", errors="replace") as stream:
                for line in stream:
                    line = line.rstrip("\n")
                    if line.strip():
                        self._logger.log(level_for(line), "%s", line)
        except Exception:  # pragma: no cover - the relay must never crash the module
            pass

    def _restore(self) -> None:
        if self._saved_fd is not None:
            try:
                os.dup2(self._saved_fd, 2)
                os.close(self._saved_fd)
            except OSError:
                pass
            self._saved_fd = None
        self.active = False


def relay_native_stderr(logger: Optional[logging.Logger] = None) -> NativeStderrRelay:
    relay = NativeStderrRelay(logger)
    relay.start()
    return relay


def configure_matplotlib_cache() -> Optional[Path]:
    """Pin matplotlib's font cache somewhere persistent and writable.

    MediaPipe imports matplotlib eagerly, and building the font cache costs
    ~20 s on a machine that has never done it. That is unavoidable once, but it
    should not recur — so point MPLCONFIGDIR at the module's own data directory
    rather than relying on whatever HOME viam-server runs with, which may be
    unset or unwritable for a background service.

    Returns the directory chosen, or None if the default was left in place.
    Must be called before anything imports matplotlib.
    """
    os.environ.setdefault("MPLBACKEND", "Agg")  # never probe a GUI backend

    if os.environ.get("MPLCONFIGDIR"):
        return None
    base = os.environ.get("VIAM_MODULE_DATA")
    if not base:
        return None
    try:
        cache = Path(base) / "matplotlib"
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        LOGGER.debug("could not create matplotlib cache dir under %s", base)
        return None
    os.environ["MPLCONFIGDIR"] = str(cache)
    return cache
