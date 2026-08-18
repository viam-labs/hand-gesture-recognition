# PyInstaller spec — onedir, not onefile.
#
# onefile re-extracts the whole ~250 MB bundle to a temp directory on every
# process start, and viam-server restarts modules on every config change. The
# larger tarball is worth the iteration speed.
#
# collect_all('mediapipe') is mandatory: MediaPipe loads its native library
# (mediapipe/tasks/c/libmediapipe.{dylib,so}) through ctypes, which PyInstaller's
# static import analysis cannot see. cv2 and matplotlib cannot be excluded —
# mediapipe imports both eagerly, even through the mediapipe.tasks entry point.

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("mediapipe")

# The .task bundle is vendored (the wheel ships no models) and resolved at
# runtime relative to sys._MEIPASS.
datas += [("models/gesture_recognizer.task", "models")]

hiddenimports += ["viam", "viam.services.vision", "viam.components.camera"]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide2", "IPython", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="main",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="main",
)
