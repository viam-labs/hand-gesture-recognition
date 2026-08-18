# hand-gesture-recognition

`viam:hand-gesture-recognition:gestures` is a Viam `vision` service that recognizes hand gestures with [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer) and reports them as detections — the gesture name as the detection label, with a bounding box around the hand.

It works with any Viam `camera` and recognizes MediaPipe's seven built-in gestures. Anything that consumes the Viam vision API can use it: trigger robot actions, gate a UI, capture gestures as data, or drive any other logic that polls a vision service.

## Setup

1. **Add the module.** In the [Viam app](https://app.viam.com), go to your machine's **CONFIGURE** tab, click **+**, and search the registry for `hand-gesture-recognition`. Add the `gestures` vision service.

2. **Configure a camera** if you do not already have one. Any Viam `camera` works; a USB webcam via the built-in `webcam` model is the usual choice.

3. **Point the service at it** — set `camera_name` in the attributes card (see [Configuration](#configuration)). That is the only attribute you have to set.

4. **Save**, and wait for the module to finish deploying.

On **Linux**, the module installs its own system libraries on first run — MediaPipe needs GL/GLES/EGL, which cannot be bundled because they have to match the host's graphics drivers. If that step cannot run (no `apt-get`, or no root), the module reports which packages to install by hand.

On **macOS**, the first time `viam-server` opens the webcam it needs camera permission. Run `viam-server` in the foreground from Terminal initially so the prompt appears — as a background daemon it can fail silently. Grant under System Settings → Privacy & Security → Camera.

## Configuration

Set this in the attributes card of the `gestures` service:

```json
{
  "camera_name": "my-camera"
}
```

`camera_name` is the only required attribute. The camera is declared as an implicit dependency, so there is no need to add it to `depends_on` — viam-server resolves it for you.

See the [gestures documentation](./docs/viam_hand-gesture-recognition_gestures.md) for every optional attribute and the full `DoCommand` reference.

## Recognized gestures

The seven built-in MediaPipe categories, emitted verbatim as detection labels:

`Closed_Fist` · `Open_Palm` · `Pointing_Up` · `Thumb_Down` · `Thumb_Up` · `Victory` · `ILoveYou`

MediaPipe's eighth category, `None`, means "a hand is visible but matches no known gesture" and is treated as absence.

## Behavior and caveats

- **Detections, not classifications.** MediaPipe already produces hand landmarks, so a bounding box costs nothing, and boxes render live on the camera stream in the Viam app — which is what makes framing, lighting, and threshold tuning something you can do by eye. It also means consumers that poll `GetDetectionsFromCamera` work without adaptation. Classifications are implemented as well, for consumers that prefer them.

- **Never opens a capture device.** Frames come from a configured Viam `camera` resource, so there is no `cv2.VideoCapture`, no AVFoundation-vs-V4L2 branching, and no contest with `viam-server` over an exclusive device handle. Requesting a camera other than the configured one returns an error.

- **Hold filter.** MediaPipe classifies each frame independently, so a hand moving between poses transiently reads as other gestures — acted on directly, a single bad frame becomes a spurious trigger. A gesture must be the top result continuously for `hold_ms` (default 400) before it counts as stable, and a single stray frame restarts the window. The window is **wall-clock, not a frame count**, because the consumer's poll rate is not ours to control — a frame count would silently mean something different at every polling interval.

- **Edge trigger.** A stable gesture fires exactly once. Holding the pose does not re-fire it; the hand must leave the frame for `clear_ms` first. Without this, a consumer that simply acts on whatever it currently sees would re-act for as long as you held the pose. With `require_clear` (default `true`), switching directly from one gesture to another also fires nothing, which forces a deliberate pause between actions.

- **Non-triggering hands are suffixed.** Because a trigger is a single-frame event, a naive implementation would show a box only on the one frame a gesture fires, which is useless for tuning. Hands that are visible but not currently triggering are reported with `unstable_suffix` (default `?`) appended — `Open_Palm?` rather than `Open_Palm`. Boxes stay on the stream, and you can watch a label lose its `?` at the moment it fires, but **consumers should treat only bare names as triggers**.

- **At most one bare label per call.** When two hands show two gestures, only the highest-confidence one triggers; the other is suffixed.

- **Recognition is serialized.** MediaPipe recognizers are not thread-safe and `recognize()` is blocking CPU work, so calls are queued behind a lock and dispatched to an executor to keep the module's event loop responsive. Concurrent callers see added latency, not corruption.

- **Reconfigure resets all state.** The recognizer is rebuilt and the hold window and latch are cleared, so a stale latch never survives a config change.

- **The filters are not a safety mechanism.** They reduce spurious triggering, but they depend on the camera, this module, and the network all being healthy. If this service fails, whatever protection it provided fails with it. Anything that moves physical hardware in response to a gesture needs an out-of-band stop that does not route through this service.

## Platform support

| Platform | Supported |
|---|---|
| macOS Apple Silicon (`darwin/arm64`) | ✅ |
| Linux x86_64 (`linux/amd64`, glibc ≥ 2.28) | ✅ |
| Linux arm64 / Raspberry Pi | ❌ no `0.10.35` wheel |
| macOS Intel | ❌ no MediaPipe wheel at any version |

MediaPipe is pinned to `0.10.35`. Versions 1.0.0 and 1.0.1 abort on macOS arm64 inside `TensorsToDetectionsCalculator::Open` → `DrishtiMetalHelper` with `graph_service.h:139 Check failed: service_ Service is unavailable` — the Metal GPU path is compiled into the graph and the Python Tasks runner never registers the Metal service. Passing `BaseOptions.Delegate.CPU` does not avoid it.

The cost of that pin is arm64 Linux: `0.10.35` publishes no `manylinux_aarch64` wheel — that arrived in 1.0.0 — so Raspberry Pi is out until upstream fixes macOS. The bug is Apple-specific, so a per-platform pin could restore it if needed.

On Linux, `libmediapipe.so` links against GL/GLES/EGL and OpenCV needs glib. `setup.sh` installs these; on a machine configured by hand, missing them shows up as `libGLESv2.so.2: cannot open shared object file`.

On macOS, the first time `viam-server` opens the webcam it needs camera permission. Run `viam-server` in the foreground from Terminal initially so the prompt appears — as a background daemon it can fail silently. Grant under System Settings → Privacy & Security → Camera.

## Manual validation

These steps verify the module on a real machine. Use the **Control** tab in the [Viam app](https://app.viam.com) or the `viam machine part run` CLI to send DoCommands.

**Prerequisites:** the service is configured and the machine is online, and the camera named in `camera_name` is present and reachable.

1. **Confirm the service loaded.**
   Open the Control tab, find the `gestures` service, and in the DoCommand panel send:
   ```json
   {"command": "status"}
   ```
   Verify the response shows the expected `camera` name and `hold_ms`, and that `latched` is `null`.

2. **Confirm the label list.**
   ```json
   {"command": "gestures"}
   ```
   These are the exact strings the service will emit as detection labels.

3. **Confirm frames are flowing, with no hand present.**
   Open the camera stream and select the `gestures` service as the overlay. With no hand in frame no boxes should appear, and `frames_seen` in `status` should climb between calls.

4. **Confirm recognition, with a hand present.**
   Hold an open palm in frame. A box should appear labeled `Open_Palm?` — the `?` means recognized but not yet triggering. If no box appears at all, the problem is framing, lighting, or `min_gesture_score`, not the filters: move closer, improve lighting, or lower `min_gesture_score`.

5. **Observe a trigger.**
   Keep holding the palm. Within `hold_ms` the label should briefly drop its `?` to read `Open_Palm`, then return to `Open_Palm?`. That single frame is the trigger. Send `{"command": "status"}` and confirm `last_fired` is `"Open_Palm"` and `latched` is `"Open_Palm"`.

6. **Confirm holding does not re-fire.**
   Keep the palm up for another 10 seconds. `seconds_since_last_fired` should keep climbing — it must not reset.

7. **Confirm clearing re-arms.**
   Drop your hand out of frame for a second, then raise the palm again. `status` should show `seconds_since_last_fired` reset to near zero.

8. **Confirm `require_clear`.**
   With the palm latched, switch directly to a fist without leaving frame. With the default `require_clear: true`, `Closed_Fist` should stay suffixed and never fire. Drop your hand, then make the fist — now it fires.

9. **Tune.**
   Raise `hold_ms` if gestures fire while you are still moving your hand into position; lower it if triggering feels sluggish. Raise `min_gesture_score` if the wrong gesture is recognized confidently. Send `{"command": "reset"}` to clear the latch without leaving frame.

### Using the Viam CLI

You can also drive DoCommands from the terminal using `viam machine part run`:

```bash
viam machine part run --machine <machine-id> --part <part-id> --resource gestures do-command '{"command":"status"}'
```

Replace `<machine-id>`, `<part-id>`, and `gestures` with your machine's values.

## Example: triggering recorded arm motions

One use of this service is driving a robot arm. [`devrel:arm-recorder:reactor`](https://github.com/viam-devrel/arm-recorder) polls a vision service and plays the recorded session mapped to a detected label, so pointing it at this service makes a hand gesture replay a pre-recorded motion:

```
camera ──► gestures ──► reactor ──► recorder ──► arm + gripper
```

Validate the vision steps above first — all of them should behave as described before an arm is connected.

1. **Record one session per gesture** you intend to use. See the [arm-recorder documentation](https://github.com/viam-devrel/arm-recorder).

2. **Set conservative speed limits on the recorder** — `max_velocity_rads_per_sec` and `max_acceleration_rads_per_sec` — before arming anything. Without them the safe-entry move runs at the arm driver's default speed and can be a large sweep from the arm's current pose.

3. **Configure the reactor** against this service, mapping bare gesture names. In the reactor's attributes card:
   ```json
   {
     "vision_service": "my-gestures",
     "camera": "my-camera",
     "recorder": "my-recorder",
     "label_sessions": {
       "Open_Palm": "wave",
       "Victory": "pick-cup"
     },
     "poll_interval_ms": 200,
     "min_confidence": 0.5,
     "cooldown_sec": 5
   }
   ```
   Note that `label_sessions` contains no `?` entries — suffixed labels exist to be visible, not to trigger.

   Unlike this service, the reactor does not declare implicit dependencies, so add `my-gestures`, `my-camera`, and `my-recorder` to its `depends_on`.

4. **Clear the workspace,** then arm the reactor with `{"command": "start_reacting"}`.

5. **Trigger one gesture** and confirm the arm plays the matching session. Send `{"command": "status"}` to the reactor and verify `last_label` and `last_session`.

6. **Disarm** with `{"command": "stop_reacting"}`, which also sends `stop_playback` to the recorder, halting any motion in progress.

> **Warning:** once armed, the arm moves autonomously in response to whatever the camera sees. The reactor has no gesture-driven stop — its only lever is `play`, and the recorder rejects a `play` while a playback is already running. Disarming from the Viam app is the only way to interrupt a motion in progress.

## Development

```bash
./setup.sh          # system libraries, venv, dependencies, and the .task model bundle
make test           # unit tests
make lint           # ruff
make module         # PyInstaller bundle + module.tar.gz
```

The 8 MB model bundle is not checked in — `setup.sh` fetches it and the build vendors it into the tarball, so the module has no network dependency at runtime.

Packaging uses PyInstaller in `--onedir` mode rather than `--onefile`: onefile re-extracts the whole ~250 MB bundle to a temp directory on every process start, and `viam-server` restarts modules on every config change. `collect_all("mediapipe")` is required because MediaPipe loads its native library through `ctypes`, which PyInstaller's static analysis cannot see. `cv2` and `matplotlib` cannot be excluded — MediaPipe imports both eagerly, even through the `mediapipe.tasks` entry point.

Tests are split so that most of them need nothing installed beyond the Python dependencies:

| File | Needs | Covers |
|---|---|---|
| `tests/test_stabilizer.py` | nothing | hold filter and edge trigger |
| `tests/test_detections.py` | nothing | label annotation, bbox math, trigger selection |
| `tests/test_recognizer.py` | `./setup.sh` | the real MediaPipe graph and image conversion |

## License

Apache 2.0 — see [LICENSE](./LICENSE).
