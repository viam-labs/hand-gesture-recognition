"""Module entry point.

Deliberately at the repo root rather than inside ``src/``, and using an absolute
import. PyInstaller executes the entry script as ``__main__`` with no parent
package, so a relative import here raises "attempted relative import with no
known parent package" — the frozen binary crashes on startup while running from
source works fine. See tests/test_entrypoint.py, which reproduces that exact
condition without needing a build.
"""

import asyncio

from viam.logging import getLogger
from viam.module.module import Module
from viam.services.vision import Vision

from src.runtime import configure_matplotlib_cache, relay_native_stderr

# Both must run before anything imports mediapipe: the matplotlib cache location
# is read at import time, and the stderr relay has to own fd 2 before the native
# library starts writing to it.
configure_matplotlib_cache()
relay_native_stderr(getLogger("mediapipe"))

from src.vision_service import GestureDetector  # noqa: E402  (see above)


async def main() -> None:
    module = Module.from_args()
    module.add_model_from_registry(Vision.API, GestureDetector.MODEL)
    await module.start()


if __name__ == "__main__":
    asyncio.run(main())
