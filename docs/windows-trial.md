# Trying the module on Windows

**What this establishes:** whether `viam:hand-gesture-recognition:gestures` runs
on Windows x86-64 at all — MediaPipe imports, the camera resolves, inference
returns detections. It runs the module **from source as a local module**, so it
touches none of the build pipeline.

**What it does not establish:** whether the module can be *published* for
Windows. That needs `windows/amd64` in `meta.json`, a Windows branch in
`setup.sh`, a per-platform `entrypoint` (PyInstaller emits `main.exe`, and the
manifest hard-codes `dist/main/main`), and a Viam cloud-build runner that accepts
the target. Do not start on those until this trial passes.

**Which modules actually have Windows builds** (checked 2026-09-08 with
`viam module download --platform windows/amd64`, which asks the registry; a
module's `meta.json` `build.arch` is the cloud-build matrix and does **not**
tell you what the registry serves):

| Module | windows/amd64 |
|---|---|
| `viam:find-webcams` | yes, 0.3.0-rc11 |
| `viam-labs:modular-webcam` | yes, 0.2.2 |
| `devrel:so101-arm` | **yes at 0.3.1**, no at 0.9.7 |
| `devrel:arm-recorder` | no (0.3.1) |
| `erh:vmodutils` | no (0.4.4) |
| `viam:hand-gesture-recognition` | no (0.1.6) — hence this trial runs it locally |

Check every version, not just `latest`: `so101-arm` shipped `windows/amd64` at
0.3.1 and dropped it by 0.9.7.

**`so101-arm` 0.3.1 on Windows fails on `first_run`, and takes the whole config
with it.** The package holds `bin/arm.exe` and `first_run.sh`, with a manifest
reading `"entrypoint": "./bin/arm.exe"` and `"first_run": "./first_run.sh"`.
`entrypoint` was made per-platform; `first_run` was not. Windows cannot exec a
shell script:

```
fork/exec ...\first_run.sh: %1 is not a valid Win32 application.
reconfiguration aborted because of error executing first run. falling back to
last config...
```

The rollback is the important part. One module's `first_run` failure aborts the
*entire* reconfiguration, so every other resource stops coming up too. On this
machine that presented as `find-webcams/webcam-discovery` returning a
ConnectError, which had nothing to do with `find-webcams`: it has a Windows
build, downloaded 0.2.1, and was never reached.

The script itself installs nlopt on Debian, so it has no business running on
Windows at all. Fix belongs in `viam-devrel/so-101`: make `first_run`
per-platform or omit it on Windows, and restore `windows/amd64` to the current
version. It is the same bug as this module's `setup.sh` exiting 1 on anything
that is not Linux or Darwin.

So the course is blocked on Windows by module packaging, not by the platform.

## Before you start

- Windows 11, x86-64. Not ARM — the wheels this module needs are `win_amd64`.
- A USB webcam.
- A Viam account, and `viam-server` installed on the Windows machine through the
  app's setup wizard.
- `git`, and a shell. Steps below are PowerShell.

## 1. Get the code and the model

```powershell
git clone https://github.com/viam-labs/hand-gesture-recognition
cd hand-gesture-recognition
mkdir models -Force
curl.exe -fsSL -o models\gesture_recognizer.task `
  "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
```

`setup.sh` normally does this, but it exits 1 on any OS that is not Linux or
Darwin — under Git Bash `uname` returns `MINGW64_NT-…`, so it refuses.

> **Checkpoint:** `models\gesture_recognizer.task` exists and is a few MB.

## 2. Install dependencies

```powershell
winget install --id=astral-sh.uv -e
uv sync --frozen
```

`--frozen` fails rather than re-locking, so you get the exact versions in
`uv.lock`. Every runtime dependency has a `win_amd64` wheel — mediapipe 0.10.33,
opencv-contrib-python 5.0.0.93, viam-sdk, numpy — so this should resolve without
building anything from source.

> **Checkpoint:** `uv sync` completes. If it tries to *compile* a package,
> stop and record which one: that means a wheel was missing for this platform.

## 3. The import test — the real question, asked cheaply

```powershell
uv run python -c "import mediapipe, cv2; print(mediapipe.__version__, cv2.__version__)"
```

This is the step most likely to fail, and it costs seconds. On Linux the same
import dies with `libGLESv2.so.2: cannot open shared object file` unless system
GL libraries are installed; `first_run.sh` installs them there and does nothing
on other platforms. Whether Windows needs an equivalent is unknown — this
answers it.

> **Checkpoint:** both versions print.
>
> If it fails on a missing DLL, **record the DLL name**. That is the Windows
> equivalent of the Linux GL problem and tells us what a `first_run` step would
> have to install.

## 4. Run the module standalone

```powershell
uv run python main.py localhost:12345 --tcp-mode
```

`--tcp-mode` is not optional on Windows. The Python SDK serves a module over
either a Unix socket or TCP, and CPython on Windows does not implement
`create_unix_server`, so the socket path this step used on macOS raises a bare
`NotImplementedError` from `Module.start()`. The flag is parsed in
`viam/module/module.py`, and `start()` branches on it to `host`/`port`.

Expect a pause of up to ~20 seconds on the very first run: MediaPipe imports
matplotlib eagerly and matplotlib builds a font cache once.

Unlike the macOS version of this step, this one **succeeds and keeps running**:
the module binds the port and waits. Ctrl+C to stop it.

> **Checkpoint:** it binds and stays up, with no traceback. Every import has
> then run for real, which is the whole point of this step.
>
> A `NotImplementedError` ending in `create_unix_server` means the `--tcp-mode`
> flag was dropped, not that anything is wrong with the module.

## 5. Wrap it for viam-server

A local module needs one executable. Create `run.bat` in the repo root:

```bat
@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0main.py" %*
```

`%*` forwards every argument through untouched, which is what makes the next
step a real test: viam-server passes the address and its own flags, and this
wrapper does not filter them. Do **not** hard-code `--tcp-mode` here. Whether
viam-server on Windows passes it is the open question step 6 answers, and
forcing the flag would hide the answer.

## 6. Register it as a local module

**`tcp_mode` is required on Windows.** viam-server does not infer it. The RDK's
module config carries a `tcp_mode` field, and without it the module is started
with a Unix socket path and dies on `create_unix_server`, exactly as in step 4.
(`VIAM_TCP_SOCKETS=true` in the environment forces it on regardless, but set the
field.)

The local-module option can be hard to find in the CONFIGURE tab's **+** menu.
The JSON editor, the `{}` icon at the top left, is the path that does not move:

```json
"modules": [
  {
    "type": "local",
    "name": "hand-gesture-recognition",
    "executable_path": "C:\\path\\to\\hand-gesture-recognition\\run.bat",
    "tcp_mode": true
  }
]
```

Backslashes are doubled because JSON escapes them. Field names come from
`config.Module` in the RDK: `name`, `executable_path`, `type` (`local` or
`registry`), `tcp_mode`.

> **Checkpoint:** the module appears in the LOGS tab and stays up. A resource
> error saying the model is *"not registered ... may be in failing module"* is
> the vision service complaining downstream, not the module's own error. If the
> module is missing from the config entirely, that is the message you get, with
> no module logs at all and no validation error, because nothing was started.

### The camera: `rdk:builtin:webcam` does not exist on Windows

Confirmed 2026-09-08 on viam-server 1.3.0, Windows. Configuring a webcam gives:

> unknown resource type: API rdk:component:camera with model
> rdk:builtin:webcam not registered

Not "no camera found" — the model is absent from the binary. The RDK registers
cameras in `components/camera/register`: `fake` unconditionally, and `ffmpeg`,
`replaypcd` and `videosource` (which provides `rdk:builtin:webcam`) behind
`//go:build !no_cgo`. The Windows binary is built with `no_cgo`, so the only
camera model it has is `rdk:builtin:fake`. The underlying reason is that
mediadevices' Windows camera driver is cgo against DirectShow.

Nothing in this module or its packaging changes that, and it holds for any Viam
vision work on Windows.

So use the fake camera, which validates everything except the pixels:

```json
{
  "name": "cam",
  "api": "rdk:component:camera",
  "model": "rdk:builtin:fake",
  "attributes": {}
}
```

> **Checkpoint:** `gestures` reports **Ready** and its Test card returns an empty
> detection list rather than an error. That proves the module configures, starts
> under viam-server, resolves its camera dependency, pulls frames and runs
> inference on Windows. It cannot prove recognition, because the fake camera
> never shows a hand.

> **Checkpoint:** the camera's **Test** card shows a live image. If the webcam
> does not appear at all, record that — it is a `viam-server` on Windows
> finding, not a module one, and it matters for the course.

## 7. Add the vision service

Add a service with model `viam:hand-gesture-recognition:gestures`, named
`gestures`:

```json
{
  "camera_name": "<your camera's name>"
}
```

> **Checkpoint:** the service reports **Ready**, and its Test card draws a
> labeled box around your hand. Try `Open_Palm` and `Thumb_Up`.

## What to record

1. Which step failed, if any, and the exact error.
2. Any missing DLL from step 3.
3. **[ANSWERED 2026-09-08] Modules need `"tcp_mode": true` on Windows.** It is
   opt-in per module in the RDK's config, not inferred from the platform. This
   is not an RDK gap, and it is not something `meta.json` or `setup.sh` can
   carry: it belongs in whatever instructions ship for Windows users.
4. **[ANSWERED 2026-09-08, then corrected] `rdk:builtin:webcam` does not exist
   on Windows**, because viam-server's Windows build is `no_cgo`. But that is
   not "no camera on Windows": a *modular* camera runs as its own process and
   is not bound by viam-server's build tags.
   `viam-labs:modular-webcam:webcam` works on Windows out of the box and offers
   a dropdown of sources. Gesture recognition runs end to end against it.
5. `viam:find-webcams` does have a Windows build and does start, but its
   discovery returned no cameras on Windows. Unresolved, and it matters: the
   course has learners add it.
6. Whether MediaPipe's startup lines arrive as ERROR in the LOGS tab. The
   fd-2 relay in `src/runtime.py` may not take on Windows — native code there
   often writes to `GetStdHandle` rather than the CRT descriptor table. It fails
   safe, so this is cosmetic, but it tells us whether the relay needs a Windows
   path.
