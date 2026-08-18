# Model viam:hand-gesture-recognition:gestures

A `vision` service that recognizes hand gestures with MediaPipe and reports them as detections, with the gesture name as the detection label and a bounding box around the hand. Works with any Viam `camera`, and any consumer of the vision API can act on the result.

## Configuration

Set these in the attributes card of the `gestures` service. `camera_name` is the only one you have to provide:

```json
{
  "camera_name": "my-camera",
  "hold_ms": 400,
  "min_gesture_score": 0.5
}
```

### Attributes

| Name | Type | Required | Description |
| ------------------- | ------ | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `camera_name` | string | **Required** | Camera component supplying frames. Declared as an implicit dependency, so it does **not** need to be listed in `depends_on`. Requesting a different camera from `GetDetectionsFromCamera` is an error. |
| `num_hands` | number | Optional | Maximum hands to track, 1–4. Only the highest-confidence gesture can trigger. Default: `2` |
| `hold_ms` | number | Optional | How long a gesture must be the top result continuously before it counts as stable. Wall-clock, not frames. Default: `400` |
| `clear_ms` | number | Optional | How long "no gesture" must persist before the latch releases and a new trigger is allowed. Prevents a momentary dropout from re-arming a still-held pose. Default: `300` |
| `require_clear` | bool | Optional | When `true`, the hand must clear between triggers — switching straight from one gesture to another fires nothing. When `false`, a different stable gesture fires immediately. Default: `true` |
| `min_gesture_score` | number | Optional | MediaPipe score floor, `[0, 1]`. Hands below it are ignored entirely. Applied before the hold filter, and independent of any threshold a consumer applies downstream. Default: `0.5` |
| `preview_unstable` | bool | Optional | Report non-triggering hands with `unstable_suffix` appended, so boxes stay visible on the camera stream. Default: `true` |
| `unstable_suffix` | string | Optional | Appended to non-triggering labels. Must not collide with any label a consumer treats as a trigger. Default: `"?"` |
| `box_padding` | number | Optional | Normalized padding added around the hand landmarks, `[0, 0.5]`. Purely cosmetic. Default: `0.06` |
| `model_path` | string | Optional | Override the `.task` bundle. Default: the vendored `gesture_recognizer.task` |

## Labels

The seven MediaPipe categories are emitted verbatim:

`Closed_Fist` · `Open_Palm` · `Pointing_Up` · `Thumb_Down` · `Thumb_Up` · `Victory` · `ILoveYou`

MediaPipe's `None` category means "hand visible, no known gesture" and is treated as absence — it releases the latch rather than triggering.

**At most one detection per call carries a bare label.** That is the trigger. Every other reported hand carries `unstable_suffix`. Consumers should treat only bare names as triggers.

## Behavior

**Hold filter.** A gesture must persist for `hold_ms` before it is stable. A single stray frame restarts the window.

**Edge trigger.** A stable gesture is emitted on exactly one call. Continuing to hold the pose reverts the label to its suffixed preview form. The hand must be absent for `clear_ms` before that gesture — or, with `require_clear`, any gesture — can fire again.

**Why both.** MediaPipe classifies per frame, so transitions between poses produce spurious classifications; the hold filter absorbs those. A consumer that acts on whatever it currently sees would then re-act for as long as the pose is held; the edge trigger absorbs that. Both belong here rather than in the consumer, because implementing them downstream would tie their behavior to that consumer's polling interval.

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

Returns the recognizable label list — useful for building a consumer's label-to-action map without consulting the docs.

### `reset`

```json
{"command": "reset"}
```

Clears the latch and hold window. Useful when tuning, so you do not have to move out of frame to re-arm.

## Tuning

1. Configure the service and open the camera stream in the Viam app **before** wiring it to anything that acts on the result.
2. Watch the suffixed labels (`Open_Palm?`) to confirm the gesture is recognized at all, and at what score. If nothing appears, the problem is framing, lighting, or `min_gesture_score` — not the filters.
3. Raise `hold_ms` if gestures fire while you are moving your hand into position. Lower it if triggering feels sluggish.
4. Raise `min_gesture_score` if the wrong gesture is recognized confidently. Lower it if a correct gesture never reaches the threshold.
5. Only after labels look right, connect the consumer that acts on them. If that consumer moves physical hardware, set its speed limits conservatively first.

## Safety

Anything that moves physical hardware in response to a gesture moves autonomously in response to whatever the camera sees. The filters here reduce spurious triggering but are **not** a safety mechanism: they depend on the camera, this module, and the network all being healthy. If this service fails, whatever protection it provided fails with it. Keep an out-of-band stop — one that does not route through this service — available.
