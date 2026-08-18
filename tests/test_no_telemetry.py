"""Guards against shipping a MediaPipe build that phones home.

MediaPipe 0.10.35 carries Google's "clearcut" telemetry client and attempts
uploads at runtime, surfacing as portable_clearcut_uploader.cc errors in
viam-server logs. It is undocumented and has no opt-out
(google-ai-edge/mediapipe#6291), and because the PyPI wheels are built inside
Google, clearcut does not appear in the public source tree — so it cannot be
audited from the repo, only from the shipped binary.

0.10.33 is the last release without it. This test reads the actual native
library that will be bundled, so a version bump that reintroduces telemetry
fails here rather than on a user's machine.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TELEMETRY_MARKERS = (b"clearcut", b"Clearcut")

#: Newest MediaPipe release with zero clearcut references. There is no 0.10.34,
#: so this is exactly the last clean version before telemetry was added.
LAST_CLEAN_VERSION = "0.10.33"


def _native_lib() -> Path:
    import mediapipe

    base = Path(mediapipe.__file__).parent / "tasks" / "c"
    for name in ("libmediapipe.dylib", "libmediapipe.so"):
        if (base / name).is_file():
            return base / name
    pytest.skip(f"no libmediapipe native library under {base}")


def test_pinned_version_is_the_last_clean_release():
    import mediapipe

    assert mediapipe.__version__ == LAST_CLEAN_VERSION, (
        f"mediapipe {mediapipe.__version__} is installed but the pin is "
        f"{LAST_CLEAN_VERSION}. Later releases embed clearcut telemetry."
    )


def test_native_library_contains_no_telemetry_client():
    lib = _native_lib()
    blob = lib.read_bytes()
    hits = {m.decode(): blob.count(m) for m in TELEMETRY_MARKERS if blob.count(m)}
    assert not hits, (
        f"{lib.name} references Google's clearcut telemetry service {hits}. "
        f"Pin mediapipe=={LAST_CLEAN_VERSION}; there is no opt-out "
        f"(google-ai-edge/mediapipe#6291)."
    )


def test_requirements_pins_an_exact_version():
    """A floating pin would silently pick up a telemetry-bearing release."""
    req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()
    line = next(
        (
            line.strip()
            for line in req.splitlines()
            if line.strip().startswith("mediapipe")
        ),
        None,
    )
    assert line == f"mediapipe=={LAST_CLEAN_VERSION}", (
        f"requirements.txt must pin mediapipe exactly, got {line!r}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
