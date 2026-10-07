from dataclasses import dataclass, asdict
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

from .models import Uncertainty

register_heif_opener(thumbnails=False)


class ImageInputError(RuntimeError):
    pass


@dataclass
class Page:
    number: int
    original: Path
    oriented: Path
    enhanced: Path | None
    width: int
    height: int
    metrics: dict[str, float]
    warnings: list[str]
    actions: list[str]

    def summary(self) -> dict:
        return asdict(self) | {"original": self.original.name, "oriented": self.oriented.name,
                             "enhanced": self.enhanced.name if self.enhanced else None}


def prepare_page(source: Path, number: int, directory: Path) -> Page:
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff", ".webp"}:
        raise ImageInputError("Use JPEG/PNG/HEIC/HEIF/TIFF/WebP.")
    original = directory / "originals" / f"page_{number:02d}{source.suffix.lower()}"
    shutil.copyfile(source, original)
    try:
        with Image.open(original) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ImageInputError("Multi-frame files must be exported as separate ordered pages")
            oriented_image = ImageOps.exif_transpose(image).convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageInputError(f"Cannot decode page {number}: {exc}") from exc
    width, height = oriented_image.size
    if min(width, height) < 160:
        raise ImageInputError(f"Page {number} has insufficient resolution ({width}x{height})")
    oriented = directory / "processed" / f"page_{number:02d}_original.png"
    oriented_image.save(oriented)  # No resizing, no recompression; retain original file too.
    rgb = np.asarray(oriented_image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Normalize measurement scale only, never the image sent to the VLM.
    ratio = min(1.0, 1600 / max(width, height))
    sample = cv2.resize(gray, None, fx=ratio, fy=ratio, interpolation=cv2.INTER_AREA)
    metrics = {"laplacian_variance": float(cv2.Laplacian(sample, cv2.CV_64F).var()),
               "mean_brightness": float(sample.mean()), "contrast_std": float(sample.std()),
               "dark_fraction": float((sample < 12).mean()),
               "clipped_white_fraction": float((sample > 250).mean())}
    warnings: list[str] = []
    actions = ["lossless EXIF orientation normalization; no resizing"]
    if min(width, height) < 1000:
        warnings.append("low_resolution")
    if metrics["laplacian_variance"] < 35:
        warnings.append("possible_blur")
    if metrics["mean_brightness"] < 50:
        warnings.append("possible_underexposure")
    if metrics["contrast_std"] < 22:
        warnings.append("possible_low_contrast")
    # A white paper background is expected. Clipping alone is not an unreadability gate.
    if metrics["clipped_white_fraction"] > .85 and metrics["contrast_std"] < 22:
        warnings.append("possible_overexposure")
    enhanced = None
    if any(w in warnings for w in ("possible_underexposure", "possible_low_contrast")):
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        lab[:, :, 0] = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        enhanced = directory / "processed" / f"page_{number:02d}_contrast.png"
        Image.fromarray(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)).save(enhanced)
        actions.append("mild CLAHE luminance variant; original retained")
    # Perspective/page completeness are semantic VLM checks. No guessed page cropping.
    return Page(number, original, oriented, enhanced, width, height, metrics, warnings, actions)


def retry_views(pages: list[Page], uncertainties: list[Uncertainty], directory: Path) -> list[tuple[str, Path]]:
    views: list[tuple[str, Path]] = []
    by_number = {p.number: p for p in pages}
    for index, uncertainty in enumerate(uncertainties[:6]):
        page = by_number.get(uncertainty.page_number)
        if page is None:
            continue
        with Image.open(page.oriented) as image:
            box = uncertainty.crop_box
            if (box and len(box) == 4 and all(0 <= v <= 1 for v in box)
                    and box[0] < box[2] and box[1] < box[3]):
                pad = .06
                rect = (int(max(0, box[0]-pad)*page.width), int(max(0, box[1]-pad)*page.height),
                        int(min(1, box[2]+pad)*page.width), int(min(1, box[3]+pad)*page.height))
                if rect[2] - rect[0] >= 32 and rect[3] - rect[1] >= 32:
                    crop = directory / "processed" / f"retry_{index:02d}_page_{page.number:02d}.png"
                    image.crop(rect).save(crop)
                    views.append((f"Detail crop of ORIGINAL PAGE {page.number}; not an additional page", crop))
    if not views:
        # Unknown location: overlapping top/bottom original crops expose smaller symbols.
        for page in pages[:3]:
            with Image.open(page.oriented) as image:
                for label, top, bottom in (("top", 0, .6), ("bottom", .4, 1)):
                    crop = directory / "processed" / f"retry_page_{page.number:02d}_{label}.png"
                    image.crop((0, int(top*page.height), page.width, int(bottom*page.height))).save(crop)
                    views.append((f"{label} detail of ORIGINAL PAGE {page.number}; not an additional page", crop))
    return views
