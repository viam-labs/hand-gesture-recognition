"""Guards the frozen-bundle entry path.

v0.1.1 shipped a module that crashed on startup with "attempted relative import
with no known parent package". Running from source was fine and every unit test
passed, because the tests import `src.vision_service` directly and nothing ever
executed the entry script the way PyInstaller does — as `__main__`, with no
parent package.

`runpy.run_path` with a non-`__main__` run name reproduces exactly that
condition: the module body executes as a standalone script, so any relative
import in it fails, but the `if __name__ == "__main__"` block does not fire.
Instant, and no build required.
"""

import runpy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_entrypoint_executes_as_a_standalone_script():
    """The exact condition PyInstaller creates. Fails on any relative import."""
    ns = runpy.run_path(str(ROOT / "main.py"), run_name="viam_module_entrypoint")
    assert "main" in ns, "entry script must define main()"


def test_entrypoint_does_not_use_relative_imports():
    """A direct read, so the failure message names the cause rather than the symptom."""
    src = (ROOT / "main.py").read_text()
    offenders = [
        line.strip()
        for line in src.splitlines()
        if line.startswith("from .") or line.startswith("import .")
    ]
    assert not offenders, (
        "main.py is the PyInstaller entry script and runs without a parent "
        f"package; relative imports crash the frozen binary: {offenders}"
    )


def test_entrypoint_lives_outside_the_src_package():
    """An entry script inside the package it imports reintroduces the ambiguity."""
    assert (ROOT / "main.py").is_file()
    assert not (ROOT / "src" / "main.py").exists()


def test_spec_points_at_the_root_entrypoint():
    spec = (ROOT / "main.spec").read_text()
    assert '["main.py"]' in spec, "main.spec must analyze the root main.py"


@pytest.mark.parametrize("name", ["src.gestures", "src.vision_service"])
def test_package_modules_import_absolutely(name):
    """src/ is a real package, so its internal relative imports are fine."""
    __import__(name)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
