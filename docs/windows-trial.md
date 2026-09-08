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

**It also cannot test the course.** `so101-arm`, `arm-recorder`, `find-webcams`
and `vmodutils` publish no Windows build either, so the arms and the recorder are
out of scope here. This is the gesture module alone.

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

Then add a **camera** component (`webcam`) and pick your USB camera.

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
4. Whether the webcam was visible to viam-server at all.
5. Whether MediaPipe's startup lines arrive as ERROR in the LOGS tab. The
   fd-2 relay in `src/runtime.py` may not take on Windows — native code there
   often writes to `GetStdHandle` rather than the CRT descriptor table. It fails
   safe, so this is cosmetic, but it tells us whether the relay needs a Windows
   path.
