"""Bounded async admission; disk IO and decoding run outside the event loop."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from io import BytesIO
from pathlib import Path
import time
import os
from uuid import uuid4
from PIL import Image, ImageOps
from fastapi import HTTPException
from .image_policy import DECODE_LOCK, ImagePolicy, check_disk


class ImageService:
    def __init__(self, config):
        self.settings = config.server
        self.policy = ImagePolicy(self.settings.max_image_pixels)
        self.uploads = asyncio.Semaphore(self.settings.max_uploads)
        self.previews = asyncio.Semaphore(self.settings.max_previews)

    @asynccontextmanager
    async def slot(self, preview=False):
        semaphore = self.previews if preview else self.uploads
        try:
            await asyncio.wait_for(semaphore.acquire(), self.settings.preview_slot_timeout_seconds)
        except TimeoutError:
            raise HTTPException(429, "image_capacity", headers={"Retry-After": "2"})
        try:
            yield
        finally:
            semaphore.release()

    async def receive(self, request, directory: Path):
        limit = self.settings.max_page_megabytes * 1024**2
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid content length")
        if length < 0 or length > limit:
            raise HTTPException(413, "page_size_limit")
        path = directory / (uuid4().hex + ".part")
        handle = None
        try:
            await asyncio.to_thread(check_disk, directory, max(length, limit), self.settings.disk_reserve_megabytes * 1024**2)
            handle = await asyncio.to_thread(path.open, "wb")
            digest = hashlib.sha256()
            count = 0
            started = time.monotonic()
            stream = request.stream().__aiter__()
            while True:
                remaining = self.settings.upload_timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError
                try:
                    chunk = await asyncio.wait_for(anext(stream), min(remaining, self.settings.upload_idle_timeout_seconds))
                except StopAsyncIteration:
                    break
                count += len(chunk)
                if count > limit:
                    raise HTTPException(413, "page_size_limit")
                await asyncio.to_thread(handle.write, chunk)
                digest.update(chunk)
            def durable_close():
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()
            await asyncio.to_thread(durable_close)
            handle = None
            if not count:
                raise HTTPException(422, "Empty image")
            return path, count, digest.hexdigest()
        except BaseException as exc:
            if handle:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(path.unlink, missing_ok=True)
            if isinstance(exc, TimeoutError):
                raise HTTPException(408, "upload_timeout") from exc
            if isinstance(exc, OSError):
                raise HTTPException(503, "storage_unavailable") from exc
            raise

    async def inspect(self, path):
        def run():
            with DECODE_LOCK:
                return self.policy.inspect(path)
        try:
            return await asyncio.to_thread(run)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def preview(self, path):
        def run():
            with DECODE_LOCK:
                self.policy.inspect(path)
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    image.thumbnail((1600, 1600))
                    data = BytesIO()
                    image.save(data, format="JPEG", quality=92)
                    return data.getvalue()
        # Keep admission reserved until the native decode ends, even after timeout.
        task = asyncio.create_task(asyncio.to_thread(run))
        try:
            return await asyncio.wait_for(asyncio.shield(task), self.settings.preview_timeout_seconds)
        except TimeoutError:
            await task
            raise HTTPException(408, "preview_timeout")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
