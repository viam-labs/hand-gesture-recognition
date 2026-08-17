"""Tests for detection assembly: edge trigger, label annotation, bbox math.

MediaPipe results are faked so these run without a camera or a real hand. The
recognizer itself is exercised in test_recognizer.py.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gestures import GestureStabilizer  # noqa: E402
from src.vision_service import GestureDetector  # noqa: E402

W, H = 640, 480


def landmarks(x0, y0, x1, y1):
    """Four corner landmarks spanning a normalized box."""
    return [
        SimpleNamespace(x=x0, y=y0),
        SimpleNamespace(x=x1, y=y0),
        SimpleNamespace(x=x0, y=y1),
        SimpleNamespace(x=x1, y=y1),
    ]


def result(*hands):
    """Fake a MediaPipe GestureRecognizerResult from (name, score, box) triples."""
    return SimpleNamespace(
        gestures=[[SimpleNamespace(category_name=n, score=s)] for n, s, _ in hands],
        hand_landmarks=[landmarks(*b) for _, _, b in hands],
    )


@pytest.fixture
def det():
    d = GestureDetector("test")
    d.camera_name = "cam"
    d.box_padding = 0.0
    d._stabilizer = GestureStabilizer(hold_ms=0.0, clear_ms=0.0)
    return d


def test_unstable_hand_is_suffixed(det):
    """Before a gesture fires, it is annotated but must not match the reactor map."""
    det._stabilizer = GestureStabilizer(hold_ms=10_000.0)  # never becomes stable
    out = det._to_detections(result(("Open_Palm", 0.9, (0.2, 0.2, 0.6, 0.6))), W, H)
    assert [d.class_name for d in out] == ["Open_Palm?"]


def test_trigger_emits_bare_label_exactly_once(det):
    r = result(("Open_Palm", 0.9, (0.2, 0.2, 0.6, 0.6)))
    assert [d.class_name for d in det._to_detections(r, W, H)] == ["Open_Palm"]
    # Holding the pose must not re-fire — it reverts to the suffixed preview.
    assert [d.class_name for d in det._to_detections(r, W, H)] == ["Open_Palm?"]
    assert [d.class_name for d in det._to_detections(r, W, H)] == ["Open_Palm?"]


def test_only_highest_confidence_hand_triggers(det):
    """Two hands, two gestures: exactly one bare label, on the stronger hand."""
    out = det._to_detections(
        result(
            ("Victory", 0.6, (0.1, 0.1, 0.3, 0.3)),
            ("Thumb_Up", 0.95, (0.6, 0.6, 0.9, 0.9)),
        ),
        W,
        H,
    )
    names = [d.class_name for d in out]
    assert names.count("Thumb_Up") == 1
    assert "Victory?" in names
    assert sum(1 for n in names if not n.endswith("?")) == 1


def test_none_category_is_ignored(det):
    assert det._to_detections(result(("None", 0.99, (0.2, 0.2, 0.6, 0.6))), W, H) == []


def test_low_score_hand_is_dropped(det):
    det.min_gesture_score = 0.7
    assert det._to_detections(result(("Victory", 0.5, (0.2, 0.2, 0.6, 0.6))), W, H) == []


def test_preview_disabled_yields_only_triggers(det):
    det.preview_unstable = False
    det._stabilizer = GestureStabilizer(hold_ms=10_000.0)
    assert det._to_detections(result(("Open_Palm", 0.9, (0.2, 0.2, 0.6, 0.6))), W, H) == []


def test_bounding_box_is_pixel_space(det):
    out = det._to_detections(result(("Victory", 0.9, (0.25, 0.5, 0.75, 1.0))), W, H)
    box = out[0]
    assert (box.x_min, box.y_min, box.x_max, box.y_max) == (160, 240, 480, 480)


def test_padding_expands_and_clamps_to_frame(det):
    det.box_padding = 0.1
    out = det._to_detections(result(("Victory", 0.9, (0.05, 0.05, 0.95, 0.95))), W, H)
    box = out[0]
    assert box.x_min == 0 and box.y_min == 0  # clamped low
    assert box.x_max == W and box.y_max == H  # clamped high


def test_degenerate_landmarks_are_skipped(det):
    """A zero-area hand must not produce an inverted or empty box."""
    assert det._to_detections(result(("Victory", 0.9, (0.5, 0.5, 0.5, 0.5))), W, H) == []


def test_clearing_rearms_the_trigger(det):
    r = result(("Open_Palm", 0.9, (0.2, 0.2, 0.6, 0.6)))
    assert [d.class_name for d in det._to_detections(r, W, H)] == ["Open_Palm"]
    det._to_detections(result(), W, H)  # hand leaves frame
    assert [d.class_name for d in det._to_detections(r, W, H)] == ["Open_Palm"]


def test_confidence_is_the_mediapipe_score(det):
    out = det._to_detections(result(("Thumb_Up", 0.83, (0.2, 0.2, 0.6, 0.6))), W, H)
    assert out[0].confidence == pytest.approx(0.83)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
