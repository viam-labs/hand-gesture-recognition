# Model viam:hand-gesture-recognition:gestures

A `vision` service that recognizes hand gestures with MediaPipe and reports them as detections, with the gesture name as the detection label and a bounding box around the hand. Intended to drive [`devrel:arm-recorder:reactor`](https://github.com/viam-devrel/arm-recorder), which maps detection labels to recorded arm sessions.

## Configuration

```json
{
  "services": [
    {
      "name": "my-gestures",
      "type": "vision",
      "model": "viam:hand-gesture-recognition:gestures",
      "attributes": {
        "camera_name": "my-camera",
        "num_hands": 2,
        "hold_ms": 400,
        "clear_ms": 300,
        "require_clear": true,
        "min_gesture_score": 0.5,
        "preview_unstable": true,
        "unstable_suffix": "?",
        "box_padding": 0.06
      },
      "depends_on": ["my-camera"]
    }
  ]
}
```

### Attributes

| Attribute | Type | Required | Default | Description |
|---|---|---|---|---|
| `camera_name` | string | yes | — | Camera component supplying frames. Must also appear in `depends_on`. Requesting a different camera from `GetDetectionsFromCamera` is an error. |
| `num_hands` | number | no | `2` | Maximum hands to track, 1–4. Only the highest-confidence gesture can trigger. |
| `hold_ms` | number | no | `400` | How long a gesture must be the top result continuously before it counts as stable. Wall-clock, not frames. |
| `clear_ms` | number | no | `300` | How long "no gesture" must persist before the latch releases and a new trigger is allowed. Prevents a momentary dropout from re-arming a still-held pose. |
| `require_clear` | bool | no | `true` | When `true`, the hand must clear between triggers — switching straight from one gesture to another fires nothing. When `false`, a different stable gesture fires immediately. |
| `min_gesture_score` | number | no | `0.5` | MediaPipe score floor, `[0, 1]`. Hands below it are ignored entirely. Distinct from the reactor's own `min_confidence`. |
| `preview_unstable` | bool | no | `true` | Report non-triggering hands with `unstable_suffix` appended, so boxes stay visible on the camera stream. |
| `unstable_suffix` | string | no | `"?"` | Appended to non-triggering labels. Must not collide with any key in the reactor's `label_sessions`. |
| `box_padding` | number | no | `0.06` | Normalized padding added around the hand landmarks, `[0, 0.5]`. Purely cosmetic. |
| `model_path` | string | no | bundled | Override the `.task` bundle. Defaults to the vendored `gesture_recognizer.task`. |

## Labels

The seven MediaPipe categories are emitted verbatim:

`Closed_Fist` · `Open_Palm` · `Pointing_Up` · `Thumb_Down` · `Thumb_Up` · `Victory` · `ILoveYou`

MediaPipe's `None` category means "hand visible, no known gesture" and is treated as absence — it releases the latch rather than triggering.

**At most one detection per call carries a bare label.** That is the trigger. Every other reported hand carries `unstable_suffix`. Map only bare names in the reactor's `label_sessions`.

## Behavior

**Hold filter.** A gesture must persist for `hold_ms` before it is stable. A single stray frame restarts the window.

**Edge trigger.** A stable gesture is emitted on exactly one call. Continuing to hold the pose reverts the label to its suffixed preview form. The hand must be absent for `clear_ms` before that gesture — or, with `require_clear`, any gesture — can fire again.

**Why both.** MediaPipe classifies per frame, so transitions between poses produce spurious classifications; the hold filter absorbs those. The reactor is level-triggered and would replay a held pose every `cooldown_sec`; the edge trigger absorbs that. Neither filter belongs in the reactor, because putting them there would tie their behavior to `poll_interval_ms`.

**Threading.** MediaPipe recognizers are not thread-safe and `recognize()` is blocking CPU work. Calls are serialized behind a lock and dispatched to an executor so the module's event loop keeps serving other RPCs.

**Reconfigure** rebuilds the recognizer and resets all stabilizer state, so a stale latch never survives a config change.

## DoCommand reference

### `status`

```json
{"command": "status"}
```

```json
{
  "camera": "my-camera",
  "frames_seen": 1420,
  "hold_ms": 400,
  "clear_ms": 300,
  "require_clear": true,
  "latched": "Open_Palm",
  "last_fired": "Open_Palm",
  "seconds_since_last_fired": 3.4
}
```

`latched` is the gesture currently blocking re-triggering; it clears when the hand leaves the frame. `last_fired` and `seconds_since_last_fired` appear only after at least one trigger.

### `gestures`

```json
{"command": "gestures"}
```

Returns the recognizable label list — useful for building a `label_sessions` map without consulting the docs.

### `reset`

```json
{"command": "reset"}
```

Clears the latch and hold window. Useful when tuning, so you do not have to move out of frame to re-arm.

## Tuning

1. Configure the service and open the camera stream in the Viam app **before** connecting anything to an arm.
2. Watch the suffixed labels (`Open_Palm?`) to confirm the gesture is recognized at all, and at what score. If nothing appears, the problem is framing, lighting, or `min_gesture_score` — not the filters.
3. Raise `hold_ms` if gestures fire while you are moving your hand into position. Lower it if triggering feels sluggish.
4. Raise `min_gesture_score` if the wrong gesture is recognized confidently. Lower it if a correct gesture never reaches the threshold.
5. Only after labels look right, wire the reactor and set conservative `max_velocity_rads_per_sec` on the recorder before calling `start_reacting`.

## Safety

Once the reactor is armed, the arm moves autonomously in response to whatever the camera sees. The filters here reduce spurious triggering but are **not** a safety mechanism: they depend on the camera, this module, and the network all being healthy. If this service fails, whatever protection it provided fails with it. Keep an out-of-band stop — physical power cutoff on the servo bus — available.
