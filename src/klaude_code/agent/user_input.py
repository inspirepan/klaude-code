from __future__ import annotations

import asyncio
from pathlib import Path

from klaude_code.llm.image import freeze_image_for_history
from klaude_code.protocol.message import UserInputPayload


async def freeze_user_input_for_history(user_input: UserInputPayload, *, images_dir: Path) -> UserInputPayload:
    input_images = user_input.images
    if not input_images:
        return user_input
    images = await asyncio.to_thread(
        lambda: [freeze_image_for_history(image, images_dir=images_dir) for image in input_images]
    )
    return user_input.model_copy(update={"images": images})
