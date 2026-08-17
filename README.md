# hand-gesture-recognition

A Viam vision service that recognizes hand gestures and reports them as **detections**, so that a hand gesture can trigger a pre-recorded robot arm motion.

`devrel:hand-gesture-recognition:gestures` wraps [MediaPipe's Gesture Recognizer](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer) and emits the recognized gesture as a detection label with a hand bounding box. It is designed to pair with [`devrel:arm-recorder:reactor`](https://github.com/viam-devrel/arm-recorder), which polls a vision service and plays the recorded session mapped to a detected label:

```
camera ──► gestures (this module) ──► reactor ──► recorder ──► arm + gripper
```

See the [model documentation](./docs/devrel_hand-gesture-recognition_gestures.md) for the full configuration and DoCommand reference.

## Why detections, not classifications

Gestures feel like a classification problem, but the reactor calls `GetDetectionsFromCamera`, so a detector plugs in with no changes anywhere else. It is also the better fit in practice: MediaPipe already produces hand landmarks, so a real bounding box costs nothing, and boxes render live on the camera stream in the Viam app — which is what makes framing, lighting, and threshold tuning something you can do by eye.

Classifications are implemented as well, for consumers that prefer them.

## Recognized gestures

The seven built-in MediaPipe categories:

`Closed_Fist` · `Open_Palm` · `Pointing_Up` · `Thumb_Down` · `Thumb_Up` · `Victory` · `ILoveYou`

MediaPipe's eighth category, `None`, means "a hand is visible but matches no known gesture." It is treated as absence.

## How a gesture becomes a trigger

MediaPipe classifies each frame independently, so a hand moving between poses transiently reads as other gestures. Feeding that directly to an arm means the arm lunges on a single bad frame. Two filters sit between recognition and output:

**Hold.** A gesture must be the top result continuously for `hold_ms` (default 400) before it counts as stable. The window is wall-clock rather than a frame count, because the caller's poll rate is not ours to control — the reactor's `poll_interval_ms` would otherwise silently redefine what "N frames" means.

**Edge trigger.** A stable gesture fires exactly once. Holding the pose does not re-fire it; the hand must leave the frame first. Without this, holding an open palm replays the session every `cooldown_sec` forever. With `require_clear` (default `true`), switching directly from one gesture to another also fires nothing — the hand must clear between triggers, which forces a deliberate pause between arm motions.

Because a trigger is a single-frame event, hands that are visible but not currently triggering are still reported, with `unstable_suffix` (default `?`) appended — `Open_Palm?` rather than `Open_Palm`. You always see boxes on the stream, and you can watch a label lose its `?` at the exact moment it fires, but only the bare name matches the reactor's `label_sessions` map.

## Camera handling

This service never opens a capture device. It resolves a configured Viam `camera` resource and receives decoded frames, which means no `cv2.VideoCapture`, no AVFoundation-vs-V4L2 branching, and no contest with `viam-server` over an exclusive device handle.

On macOS, the first time `viam-server` opens the webcam it needs camera permission. Run `viam-server` in the foreground from Terminal initially so the prompt appears — as a background daemon it can fail silently. Grant under System Settings → Privacy & Security → Camera.

## Platform support

| Platform | Supported |
|---|---|
| macOS Apple Silicon (`darwin/arm64`) | ✅ |
| Linux x86_64 (`linux/amd64`, glibc ≥ 2.28) | ✅ |
| Linux arm64 / Raspberry Pi | ❌ see below |
| macOS Intel | ❌ MediaPipe publishes no `macosx_x86_64` wheel |

MediaPipe is pinned to `0.10.35`. Versions 1.0.0 and 1.0.1 abort on macOS arm64 inside `TensorsToDetectionsCalculator::Open` → `DrishtiMetalHelper` with `graph_service.h:139 Check failed: service_ Service is unavailable` — the Metal GPU path is compiled into the graph and the Python Tasks runner never registers the Metal service. Passing `BaseOptions.Delegate.CPU` does not avoid it.

The cost of that pin is arm64 Linux: `0.10.35` publishes no `manylinux_aarch64` wheel (that arrived in 1.0.0), so Raspberry Pi is out until upstream fixes macOS. The bug is Apple-specific, so a per-platform pin could restore it if needed.

## Development

```bash
./setup.sh          # venv, dependencies, and download the .task model bundle
make test           # unit tests
make module         # PyInstaller bundle + module.tar.gz
```

The model bundle is not checked in — `setup.sh` fetches it, and the build vendors it into the tarball so there is no network dependency at runtime.

Packaging uses PyInstaller in `--onedir` mode rather than `--onefile`: onefile re-extracts the whole ~250 MB bundle to a temp directory on every process start, and `viam-server` restarts modules on every config change. `collect_all("mediapipe")` is required because MediaPipe loads its native library through `ctypes`, which PyInstaller's static analysis cannot see.

## License

Apache 2.0 — see [LICENSE](./LICENSE).
