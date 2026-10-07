from dataclasses import dataclass
from pathlib import Path
import shutil
from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener(thumbnails=False)
DECODE_LOCK = __import__('threading').BoundedSemaphore(1)


@dataclass(frozen=True)
class ImagePolicy:
    max_pixels: int = 64_000_000
    min_side: int = 160

    def inspect(self, source):
        try:
            with Image.open(source) as image:
                if image.format not in {"JPEG", "PNG", "HEIF", "WEBP", "TIFF"} or getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Use a single-frame JPEG/PNG/HEIC/HEIF/WebP/TIFF")
                width, height = image.size
                if width * height > self.max_pixels:
                    raise ValueError("image_pixel_limit")
                if min(width, height) < self.min_side:
                    raise ValueError("Image resolution is too low")
                result = {"width": width, "height": height, "format": image.format}
                image.verify()
            # Verify is format-dependent; load checks truncated JPEG/HEIF too.
            if hasattr(source, "seek"):
                source.seek(0)
            with Image.open(source) as image:
                image.load()
            return result
        except (OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid image") from exc


def check_disk(path: Path, incoming: int, reserve: int = 2 * 1024**3):
    if shutil.disk_usage(path).free < incoming + reserve:
        raise OSError("insufficient_disk_space")


def check_prepared(directory: Path, maximum: int):
    if sum(p.stat().st_size for p in (directory / "processed").glob("*.png")) > maximum:
        raise ValueError("prepared_image_limit: originals retained; no automatic downscaling")
