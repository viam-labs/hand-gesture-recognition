"""Tests for the hold filter and edge trigger.

These run without MediaPipe, a camera, or an arm — which is the point of keeping
the logic in a pure module.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gestures import GestureStabilizer  # noqa: E402


def feed(stab, label, start, duration_s, step_s=0.05):
    """Feed a label steadily for a duration; return every emitted trigger."""
    fired, t = [], start
    while t < start + duration_s:
        out = stab.update(label, t)
        if out is not None:
            fired.append((out, t))
        t += step_s
    return fired


def test_brief_gesture_does_not_fire():
    stab = GestureStabilizer(hold_ms=400)
    assert feed(stab, "Open_Palm", 0.0, 0.3) == []


def test_held_gesture_fires_once():
    stab = GestureStabilizer(hold_ms=400)
    fired = feed(stab, "Open_Palm", 0.0, 3.0)
    assert [f[0] for f in fired] == ["Open_Palm"]


def test_fires_only_after_hold_elapses():
    stab = GestureStabilizer(hold_ms=400)
    fired = feed(stab, "Victory", 10.0, 2.0)
    assert len(fired) == 1
    assert fired[0][1] - 10.0 >= 0.4


def test_flicker_resets_the_hold_window():
    """A single stray frame mid-hold restarts the clock — no trigger."""
    stab = GestureStabilizer(hold_ms=400)
    t = 0.0
    for _ in range(7):  # 350ms of Open_Palm, just short of stable
        assert stab.update("Open_Palm", t) is None
        t += 0.05
    assert stab.update("Closed_Fist", t) is None  # stray frame
    t += 0.05
    for _ in range(7):  # another 350ms — still short
        assert stab.update("Open_Palm", t) is None
        t += 0.05


def test_clearing_rearms_the_same_gesture():
    stab = GestureStabilizer(hold_ms=400, clear_ms=300)
    assert len(feed(stab, "Thumb_Up", 0.0, 1.0)) == 1
    feed(stab, None, 1.0, 0.5)  # hand drops
    assert len(feed(stab, "Thumb_Up", 1.5, 1.0)) == 1


def test_brief_clear_does_not_rearm():
    """A momentary dropout must not let a still-held gesture re-fire."""
    stab = GestureStabilizer(hold_ms=400, clear_ms=300)
    assert len(feed(stab, "Thumb_Up", 0.0, 1.0)) == 1
    stab.update(None, 1.0)
    stab.update(None, 1.1)  # only 100ms of absence
    assert feed(stab, "Thumb_Up", 1.2, 1.0) == []


def test_require_clear_blocks_direct_switch():
    stab = GestureStabilizer(hold_ms=400, require_clear=True)
    assert len(feed(stab, "Open_Palm", 0.0, 1.0)) == 1
    assert feed(stab, "Victory", 1.0, 1.0) == []  # never cleared


def test_without_require_clear_direct_switch_fires():
    stab = GestureStabilizer(hold_ms=400, require_clear=False)
    assert len(feed(stab, "Open_Palm", 0.0, 1.0)) == 1
    assert len(feed(stab, "Victory", 1.0, 1.0)) == 1


def test_is_stable_does_not_consume_the_trigger():
    stab = GestureStabilizer(hold_ms=400)
    t = 0.0
    for _ in range(10):
        stab.update("Victory", t)
        t += 0.05
    stab.reset()
    t = 0.0
    for _ in range(9):
        stab.update("Victory", t)
        t += 0.05
    assert stab.is_stable("Victory", t)
    assert stab.is_stable("Victory", t)  # repeatable, no state change
    assert stab.update("Victory", t) == "Victory"  # trigger still available


def test_reset_clears_latch():
    stab = GestureStabilizer(hold_ms=400)
    assert len(feed(stab, "Open_Palm", 0.0, 1.0)) == 1
    stab.reset()
    assert len(feed(stab, "Open_Palm", 1.0, 1.0)) == 1


def test_slow_polling_still_honors_wall_clock():
    """At a 500ms poll interval, two samples already exceed a 400ms hold."""
    stab = GestureStabilizer(hold_ms=400)
    assert stab.update("Open_Palm", 0.0) is None
    assert stab.update("Open_Palm", 0.5) == "Open_Palm"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
