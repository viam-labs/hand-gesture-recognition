"""Tests for native-runtime housekeeping.

The stderr relay manipulates file descriptor 2, so these tests exercise it
against real pipes rather than mocks — a mock would not catch the failure that
matters, which is a feedback loop between the logger and the descriptor it
writes to.
"""

import logging
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.runtime import (  # noqa: E402
    NativeStderrRelay,
    configure_matplotlib_cache,
    level_for,
)


@pytest.mark.parametrize(
    "line,expected",
    [
        ("I0000 00:00:1787068812.615497 8507068 gl_context.cc:407] GL version", logging.INFO),
        ("W0000 00:00:1787066712.230265 8463189 inference_feedback_manager.cc:121] x", logging.WARNING),
        ("E0000 00:00:1787067493.634900 8475480 portable_clearcut_uploader.cc:90] y", logging.ERROR),
        ("F0000 00:00:1787066712.176972 8463184 graph_service.h:139] Check failed", logging.CRITICAL),
        ("INFO: Created TensorFlow Lite XNNPACK delegate for CPU.", logging.INFO),
        ("WARNING: something", logging.WARNING),
        ("=== Source Location Trace: ===", logging.INFO),
        ("Matplotlib is building the font cache; this may take a moment.", logging.INFO),
    ],
)
def test_level_classification(line, expected):
    assert level_for(line) == expected


def test_unrecognized_output_is_info_not_error():
    """The whole point: chatty native output must not read as failure."""
    assert level_for("some unstructured native chatter") == logging.INFO


def test_relay_captures_native_writes_to_fd_2(caplog):
    relay = NativeStderrRelay(logging.getLogger("test.relay"))
    assert relay.start()
    try:
        with caplog.at_level(logging.INFO, logger="test.relay"):
            # Bypass sys.stderr entirely, the way C++ does.
            os.write(2, b"I0000 00:00:1 1 gl_context.cc:407] GL version: 2.1\n")
            os.write(2, b"W0000 00:00:1 1 feedback.cc:121] disabling feedback\n")
            deadline = time.time() + 5
            while len(caplog.records) < 2 and time.time() < deadline:
                time.sleep(0.02)
    finally:
        relay._restore()

    levels = {r.levelno for r in caplog.records}
    assert logging.INFO in levels
    assert logging.WARNING in levels
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_python_stderr_bypasses_the_relay():
    """sys.stderr must keep pointing at the real descriptor, or logging loops."""
    relay = NativeStderrRelay(logging.getLogger("test.bypass"))
    assert relay.start()
    try:
        assert sys.stderr.fileno() != 2
    finally:
        relay._restore()


def test_relay_is_idempotent():
    relay = NativeStderrRelay(logging.getLogger("test.idem"))
    assert relay.start()
    try:
        assert relay.start()  # second call is a no-op, not a second redirect
    finally:
        relay._restore()


def test_matplotlib_cache_uses_module_data(tmp_path, monkeypatch):
    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.setenv("VIAM_MODULE_DATA", str(tmp_path))
    chosen = configure_matplotlib_cache()
    assert chosen == tmp_path / "matplotlib"
    assert chosen.is_dir()
    assert os.environ["MPLCONFIGDIR"] == str(chosen)
    assert os.environ["MPLBACKEND"] == "Agg"


def test_matplotlib_cache_respects_an_explicit_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", "/somewhere/else")
    monkeypatch.setenv("VIAM_MODULE_DATA", str(tmp_path))
    assert configure_matplotlib_cache() is None
    assert os.environ["MPLCONFIGDIR"] == "/somewhere/else"


def test_matplotlib_cache_without_module_data_is_a_noop(monkeypatch):
    """Running from source, outside viam-server: leave the default alone."""
    monkeypatch.delenv("MPLCONFIGDIR", raising=False)
    monkeypatch.delenv("VIAM_MODULE_DATA", raising=False)
    assert configure_matplotlib_cache() is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
