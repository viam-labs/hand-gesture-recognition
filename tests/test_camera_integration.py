"""Exercises the camera path against a real Camera subclass.

v0.1.2 registered and started cleanly, then failed on the first detection call
with "'CameraClient' object has no attribute 'get_image'". The Camera API has no
such method — it has get_images(), returning (Sequence[NamedImage], metadata).

Nothing caught it because the only test touching _grab asserted a *rejection*
and returned before reaching the camera. The fake below subclasses the real
viam.components.camera.Camera ABC, so calling any method that does not exist on
the interface fails here exactly as it does against a live CameraClient.
"""

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from viam.components.camera import Camera
from viam.media.utils.pil import pil_to_viam_image
from viam.media.video import CameraMimeType, NamedImage

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.vision_service import GestureDetector, _bundled_model_path  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _bundled_model_path().is_file(), reason="model not vendored; run ./setup.sh"
)


class FakeCamera(Camera):
    """A real Camera, backed by a synthetic frame."""

    def __init__(self, name: str = "cam", frames: int = 1, size=(640, 480)):
        super().__init__(name)
        self._frames = frames
        self._size = size
        self.calls = 0

    async def get_images(self, **kwargs):
        self.calls += 1
        w, h = self._size
        blank = pil_to_viam_image(
            Image.fromarray(np.zeros((h, w, 3), np.uint8), "RGB"), CameraMimeType.PNG
        )
        imgs = [
            NamedImage(f"src{i}", blank.data, blank.mime_type)
            for i in range(self._frames)
        ]
        return imgs, None

    async def get_point_cloud(self, **kwargs):
        raise NotImplementedError

    async def get_properties(self, **kwargs):
        raise NotImplementedError


@pytest.fixture
def detector():
    d = GestureDetector("test")
    d.camera_name = "cam"
    d._camera = FakeCamera("cam")
    d._recognizer = d._build_recognizer(str(_bundled_model_path()))
    yield d
    d._close_recognizer()


def test_grab_uses_a_method_that_exists_on_the_camera_api(detector):
    """The regression. Any nonexistent Camera method raises AttributeError here."""
    img = asyncio.run(detector._grab("cam"))
    assert img.data
    assert detector._camera.calls == 1


def test_detections_from_camera_end_to_end(detector):
    assert asyncio.run(detector.get_detections_from_camera("cam")) == []
    assert detector._frames_seen == 1


def test_classifications_from_camera_end_to_end(detector):
    assert asyncio.run(detector.get_classifications_from_camera("cam", 1)) == []


def test_capture_all_from_camera_returns_the_image(detector):
    res = asyncio.run(
        detector.capture_all_from_camera("cam", return_image=True, return_detections=True)
    )
    assert res.image is not None
    assert res.detections == []


def test_multi_source_camera_uses_the_first_frame(detector):
    detector._camera = FakeCamera("cam", frames=3)
    assert asyncio.run(detector._grab("cam")).data


def test_camera_returning_no_frames_is_a_clear_error(detector):
    detector._camera = FakeCamera("cam", frames=0)
    with pytest.raises(RuntimeError, match="returned no images"):
        asyncio.run(detector._grab("cam"))


def test_grab_still_rejects_a_different_camera(detector):
    with pytest.raises(ValueError, match="configured for camera 'cam'"):
        asyncio.run(detector._grab("other"))
    assert detector._camera.calls == 0


def test_unconfigured_camera_is_a_clear_error(detector):
    detector._camera = None
    with pytest.raises(RuntimeError, match="camera dependency is not configured"):
        asyncio.run(detector._grab("cam"))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
