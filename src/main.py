"""Module entry point."""

import asyncio

from viam.module.module import Module
from viam.services.vision import Vision

from .vision_service import GestureDetector


async def main() -> None:
    module = Module.from_args()
    module.add_model_from_registry(Vision.API, GestureDetector.MODEL)
    await module.start()


if __name__ == "__main__":
    asyncio.run(main())
