"""End-to-end test of the real MediaPipe recognizer and image conversion.

Unlike the other test modules this loads the actual .task bundle, so it needs
./setup.sh to have run. It does not need a camera or an arm.
"""

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from viam.media.utils.pil import pil_to_viam_image
from viam.media.video import CameraMimeType

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.vision_service import GestureDetector, _bundled_model_path  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _bundled_model_path().is_file(), reason="model not vendored; run ./setup.sh"
)


@pytest.fixture
def detector():
    d = GestureDetector("test")
    d.camera_name = "cam"
    d._recognizer = d._build_recognizer(str(_bundled_model_path()))
    yield d
    d._close_recognizer()


def viam_image(arr):
    return pil_to_viam_image(Image.fromarray(arr, "RGB"), CameraMimeType.PNG)


def test_recognizer_loads_the_bundled_model(detector):
    assert detector._recognizer is not None


def test_blank_frame_yields_no_detections(detector):
    img = viam_image(np.zeros((480, 640, 3), np.uint8))
    assert asyncio.run(detector._detect(img)) == []


def test_noise_frame_does_not_crash(detector):
    """Random input must be handled, not abort the process."""
    rng = np.random.default_rng(0)
    img = viam_image(rng.integers(0, 255, (480, 640, 3), dtype=np.uint8))
    assert isinstance(asyncio.run(detector._detect(img)), list)


def test_non_square_frames_are_handled(detector):
    for w, h in ((320, 240), (1280, 720), (480, 640)):
        img = viam_image(np.zeros((h, w, 3), np.uint8))
        assert asyncio.run(detector._detect(img)) == []


def test_repeated_calls_are_stable(detector):
    """The recognizer is reused across calls; it must not degrade or leak state."""
    img = viam_image(np.zeros((480, 640, 3), np.uint8))

    async def run():
        return [await detector._detect(img) for _ in range(20)]

    assert all(r == [] for r in asyncio.run(run()))
    assert detector._frames_seen == 20


def test_concurrent_calls_are_serialized(detector):
    """MediaPipe recognizers are not thread-safe — the lock must hold."""
    img = viam_image(np.zeros((480, 640, 3), np.uint8))

    async def run():
        return await asyncio.gather(*(detector._detect(img) for _ in range(8)))

    assert all(r == [] for r in asyncio.run(run()))


def test_grab_rejects_a_different_camera(detector):
    with pytest.raises(ValueError, match="configured for camera 'cam'"):
        asyncio.run(detector._grab("some-other-camera"))


def test_do_command_status(detector):
    status = asyncio.run(detector.do_command({"command": "status"}))
    assert status["camera"] == "cam"
    assert status["latched"] is None


def test_do_command_rejects_unknown_verb(detector):
    with pytest.raises(ValueError, match="unknown command"):
        asyncio.run(detector.do_command({"command": "explode"}))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
