"""Viam vision service that reports hand gestures as detections.

Emits MediaPipe gesture names as detection labels so that
``devrel:arm-recorder:reactor`` — which polls ``GetDetectionsFromCamera`` and
maps labels to recorded sessions — can drive an arm with zero changes.

Detections rather than classifications is deliberate: it is what the reactor
calls, MediaPipe hands us a real hand bounding box anyway, and boxes render on
the camera stream in the Viam app, which is what makes framing and lighting
tunable by eye. Classifications are implemented too, for other consumers.

This service never opens a capture device. Frames arrive from a configured Viam
``camera`` resource, so there is no ``cv2.VideoCapture``, no AVFoundation vs
V4L2 branching, and no contest with viam-server over an exclusive handle.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Final, List, Optional, Tuple

import numpy as np
from typing_extensions import Self
from viam.components.camera import Camera
from viam.logging import getLogger
from viam.media.utils.pil import viam_to_pil_image
from viam.media.video import ViamImage
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import PointCloudObject, ResourceName
from viam.proto.service.vision import Classification, Detection, GetPropertiesResponse
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.services.vision import CaptureAllResult, Vision
from viam.utils import ValueTypes, struct_to_dict

from .gestures import GestureStabilizer

LOGGER = getLogger(__name__)

MODEL_FILENAME: Final = "gesture_recognizer.task"

#: MediaPipe's category for "a hand is visible but matches no known gesture".
#: Treated as absence so it releases the stabilizer latch.
NO_GESTURE: Final = "None"

BUILTIN_GESTURES: Final = (
    "Closed_Fist",
    "Open_Palm",
    "Pointing_Up",
    "Thumb_Down",
    "Thumb_Up",
    "Victory",
    "ILoveYou",
)


def _bundled_model_path() -> Path:
    """Locate the vendored ``.task`` bundle, frozen or not.

    The MediaPipe wheel ships no model files, so the bundle is vendored into the
    module tarball. Under PyInstaller it lands beside ``sys._MEIPASS``.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "models" / MODEL_FILENAME
    return Path(__file__).resolve().parents[1] / "models" / MODEL_FILENAME


class GestureDetector(Vision, EasyResource):
    """Recognizes hand gestures and reports them as vision detections."""

    MODEL: ClassVar[str] = "devrel:hand-gesture-recognition:gestures"

    # --- configuration, populated in reconfigure ---
    camera_name: str = ""
    num_hands: int = 2
    min_gesture_score: float = 0.5
    box_padding: float = 0.06
    preview_unstable: bool = True
    unstable_suffix: str = "?"

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._recognizer: Optional[Any] = None
        self._lock = asyncio.Lock()
        self._camera: Optional[Camera] = None
        self._stabilizer = GestureStabilizer()
        self._last_fired: Optional[str] = None
        self._last_fired_at: Optional[float] = None
        self._frames_seen = 0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def new(
        cls, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> Self:
        svc = cls(config.name)
        svc.reconfigure(config, dependencies)
        return svc

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """Validate attributes and declare the camera as an implicit dependency."""
        attrs = struct_to_dict(config.attributes)

        camera = attrs.get("camera_name", "")
        if not isinstance(camera, str) or not camera.strip():
            raise ValueError("'camera_name' is required and must be a non-empty string")

        num_hands = attrs.get("num_hands", 2)
        if not isinstance(num_hands, (int, float)) or not 1 <= int(num_hands) <= 4:
            raise ValueError("'num_hands' must be between 1 and 4")

        for key, lo, hi in (
            ("min_gesture_score", 0.0, 1.0),
            ("box_padding", 0.0, 0.5),
        ):
            val = attrs.get(key)
            if val is not None and (
                not isinstance(val, (int, float)) or not lo <= float(val) <= hi
            ):
                raise ValueError(f"'{key}' must be a number in [{lo}, {hi}]")

        for key in ("hold_ms", "clear_ms"):
            val = attrs.get(key)
            if val is not None and (not isinstance(val, (int, float)) or float(val) < 0):
                raise ValueError(f"'{key}' must be a non-negative number")

        model_path = attrs.get("model_path")
        if model_path is not None and not isinstance(model_path, str):
            raise ValueError("'model_path' must be a string")

        return [camera.strip()], []

    def reconfigure(
        self, config: ComponentConfig, dependencies: Mapping[ResourceName, ResourceBase]
    ) -> None:
        attrs = struct_to_dict(config.attributes)

        self.camera_name = str(attrs.get("camera_name", "")).strip()
        self.num_hands = int(attrs.get("num_hands", 2))
        self.min_gesture_score = float(attrs.get("min_gesture_score", 0.5))
        self.box_padding = float(attrs.get("box_padding", 0.06))
        self.preview_unstable = bool(attrs.get("preview_unstable", True))
        self.unstable_suffix = str(attrs.get("unstable_suffix", "?"))

        self._stabilizer = GestureStabilizer(
            hold_ms=float(attrs.get("hold_ms", 400.0)),
            clear_ms=float(attrs.get("clear_ms", 300.0)),
            require_clear=bool(attrs.get("require_clear", True)),
        )
        self._last_fired = None
        self._last_fired_at = None
        self._frames_seen = 0

        cam_resource = dependencies.get(Camera.get_resource_name(self.camera_name))
        if cam_resource is None:
            raise ValueError(
                f"camera '{self.camera_name}' not found in dependencies; "
                f"add it to this service's 'depends_on'"
            )
        self._camera = cast_camera(cam_resource)

        model_path = str(attrs.get("model_path", "") or "") or str(_bundled_model_path())
        if not os.path.isfile(model_path):
            raise ValueError(
                f"gesture model not found at '{model_path}'. Run ./setup.sh to "
                f"download it, or set 'model_path' to an existing .task bundle."
            )

        self._close_recognizer()
        self._recognizer = self._build_recognizer(model_path)
        LOGGER.info(
            "gesture detector ready: camera=%s hands=%d hold=%.0fms model=%s",
            self.camera_name,
            self.num_hands,
            self._stabilizer.hold_ms,
            model_path,
        )

    def _build_recognizer(self, model_path: str) -> Any:
        # Imported lazily so validate_config stays cheap and import errors surface
        # against a specific config rather than at module load.
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        options = mp_vision.GestureRecognizerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=model_path),
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=self.num_hands,
        )
        return mp_vision.GestureRecognizer.create_from_options(options)

    def _close_recognizer(self) -> None:
        if self._recognizer is not None:
            try:
                self._recognizer.close()
            except Exception:  # pragma: no cover - best effort teardown
                LOGGER.debug("recognizer close failed", exc_info=True)
            self._recognizer = None

    async def close(self) -> None:
        self._close_recognizer()

    # ------------------------------------------------------------------
    # recognition
    # ------------------------------------------------------------------

    def _recognize(self, rgb: np.ndarray) -> Any:
        import mediapipe as mp

        assert self._recognizer is not None
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        return self._recognizer.recognize(image)

    def _to_detections(self, result: Any, width: int, height: int) -> List[Detection]:
        """Apply the hold filter and edge trigger, then build detections.

        At most one detection carries a bare gesture name — the one that fired
        this call. Every other visible hand is annotated with ``unstable_suffix``
        so it shows on the camera stream without matching the reactor's label
        map.
        """
        now = time.monotonic()
        self._frames_seen += 1

        hands = []
        for idx, categories in enumerate(result.gestures or []):
            if not categories:
                continue
            top = categories[0]
            name = top.category_name
            if name == NO_GESTURE or top.score < self.min_gesture_score:
                continue
            landmarks = (
                result.hand_landmarks[idx] if idx < len(result.hand_landmarks) else []
            )
            hands.append((name, float(top.score), landmarks))

        hands.sort(key=lambda h: h[1], reverse=True)
        primary = hands[0][0] if hands else None

        fired = self._stabilizer.update(primary, now)
        if fired is not None:
            self._last_fired = fired
            self._last_fired_at = now
            LOGGER.info("gesture triggered: %s", fired)

        detections: List[Detection] = []
        for position, (name, score, landmarks) in enumerate(hands):
            is_trigger = fired is not None and position == 0
            if is_trigger:
                label = name
            elif self.preview_unstable:
                label = f"{name}{self.unstable_suffix}"
            else:
                continue
            box = self._bounding_box(landmarks, width, height)
            if box is None:
                continue
            x_min, y_min, x_max, y_max = box
            detections.append(
                Detection(
                    x_min=x_min,
                    y_min=y_min,
                    x_max=x_max,
                    y_max=y_max,
                    confidence=score,
                    class_name=label,
                )
            )
        return detections

    def _bounding_box(
        self, landmarks: Sequence[Any], width: int, height: int
    ) -> Optional[Tuple[int, int, int, int]]:
        """Pixel bbox around the hand landmarks, padded and clamped to frame."""
        if not landmarks:
            return None
        xs = [lm.x for lm in landmarks]
        ys = [lm.y for lm in landmarks]
        pad = self.box_padding
        x_min = max(0.0, min(xs) - pad)
        x_max = min(1.0, max(xs) + pad)
        y_min = max(0.0, min(ys) - pad)
        y_max = min(1.0, max(ys) + pad)
        box = (
            int(x_min * width),
            int(y_min * height),
            int(x_max * width),
            int(y_max * height),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        return box

    async def _detect(self, image: ViamImage) -> List[Detection]:
        pil = viam_to_pil_image(image)
        rgb = np.ascontiguousarray(np.array(pil.convert("RGB"), dtype=np.uint8))
        height, width = rgb.shape[:2]

        # MediaPipe recognizers are not thread-safe, and recognize() is blocking
        # CPU work — serialize it and keep it off the event loop.
        async with self._lock:
            if self._recognizer is None:
                raise RuntimeError("gesture recognizer is not configured")
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._recognize, rgb)
            return self._to_detections(result, width, height)

    async def _grab(self, camera_name: str) -> ViamImage:
        if camera_name and camera_name != self.camera_name:
            raise ValueError(
                f"this service is configured for camera '{self.camera_name}', "
                f"but '{camera_name}' was requested"
            )
        if self._camera is None:
            raise RuntimeError("camera dependency is not configured")
        return await self._camera.get_image()

    # ------------------------------------------------------------------
    # Vision API
    # ------------------------------------------------------------------

    async def get_detections_from_camera(
        self, camera_name: str, *, extra: Optional[Mapping[str, Any]] = None, timeout: Optional[float] = None
    ) -> List[Detection]:
        return await self._detect(await self._grab(camera_name))

    async def get_detections(
        self, image: ViamImage, *, extra: Optional[Mapping[str, Any]] = None, timeout: Optional[float] = None
    ) -> List[Detection]:
        return await self._detect(image)

    async def get_classifications(
        self,
        image: ViamImage,
        count: int,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> List[Classification]:
        detections = await self._detect(image)
        return [
            Classification(class_name=d.class_name, confidence=d.confidence)
            for d in detections[: max(count, 0)]
        ]

    async def get_classifications_from_camera(
        self,
        camera_name: str,
        count: int,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> List[Classification]:
        return await self.get_classifications(
            await self._grab(camera_name), count, extra=extra, timeout=timeout
        )

    async def capture_all_from_camera(
        self,
        camera_name: str,
        return_image: bool = False,
        return_classifications: bool = False,
        return_detections: bool = False,
        return_object_point_clouds: bool = False,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> CaptureAllResult:
        image = await self._grab(camera_name)
        result = CaptureAllResult(image=image if return_image else None)
        if return_detections or return_classifications:
            detections = await self._detect(image)
            if return_detections:
                result.detections = detections
            if return_classifications:
                result.classifications = [
                    Classification(class_name=d.class_name, confidence=d.confidence)
                    for d in detections
                ]
        return result

    async def get_object_point_clouds(
        self, camera_name: str, *, extra: Optional[Mapping[str, Any]] = None, timeout: Optional[float] = None
    ) -> List[PointCloudObject]:
        raise NotImplementedError("gesture detection does not produce point clouds")

    async def get_properties(
        self, *, extra: Optional[Mapping[str, Any]] = None, timeout: Optional[float] = None
    ) -> GetPropertiesResponse:
        return GetPropertiesResponse(
            classifications_supported=True,
            detections_supported=True,
            object_point_clouds_supported=False,
        )

    async def do_command(
        self, command: Mapping[str, ValueTypes], *, timeout: Optional[float] = None, **kwargs
    ) -> Mapping[str, ValueTypes]:
        verb = command.get("command")
        if verb == "status":
            since = (
                time.monotonic() - self._last_fired_at
                if self._last_fired_at is not None
                else None
            )
            status: dict = {
                "camera": self.camera_name,
                "frames_seen": self._frames_seen,
                "hold_ms": self._stabilizer.hold_ms,
                "clear_ms": self._stabilizer.clear_ms,
                "require_clear": self._stabilizer.require_clear,
                "latched": self._stabilizer.latched,
            }
            if self._last_fired is not None:
                status["last_fired"] = self._last_fired
                status["seconds_since_last_fired"] = round(since, 2) if since else 0.0
            return status
        if verb == "gestures":
            return {"gestures": list(BUILTIN_GESTURES)}
        if verb == "reset":
            self._stabilizer.reset()
            return {"status": "reset"}
        raise ValueError(
            f"unknown command '{verb}'; expected one of: status, gestures, reset"
        )


def cast_camera(resource: ResourceBase) -> Camera:
    """Narrow a dependency to a Camera with a clear error if it is not one."""
    if not isinstance(resource, Camera):
        raise ValueError(f"resource '{resource}' is not a camera")
    return resource
