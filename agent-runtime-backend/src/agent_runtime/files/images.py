"""Preparing an image file of any format for a vision model.

OpenAI accepts PNG, JPEG, WEBP and non-animated GIF. Everything else
Pillow can open (BMP, TIFF, ICO, PSD, AVIF, HEIC with `pillow-heif`, ...)
is converted, so the model never sees "unsupported format". Every image is
also oriented by its EXIF tag and scaled to fit `max_dimension`, which
bounds both the request size and the tokens an image costs.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from agent_runtime.agent.messages import ImageAttachment

try:  # Optional: HEIC/HEIF (iPhone photos) need an extra plugin.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - depends on the environment
    pass

RASTER_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif", ".webp", ".bmp", ".dib",
        ".tif", ".tiff", ".ico", ".icns", ".heic", ".heif", ".avif", ".tga", ".ppm",
        ".pgm", ".pbm", ".pnm", ".pcx", ".psd", ".dds", ".jp2", ".j2k", ".qoi",
    }
)  # fmt: skip

# A lossless PNG of a photo can be several megabytes; past this, a
# high-quality JPEG carries the same information for the model in far less.
_PNG_BUDGET_BYTES = 1_500_000

Detail = Literal["auto", "low", "high"]


class ImageError(Exception):
    """The file is not an image Pillow can decode."""


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """An image ready for the model, plus what was done to it on the way."""

    attachment: ImageAttachment
    source_format: str
    original_size: tuple[int, int]
    sent_size: tuple[int, int]
    frames: int

    def summary(self, display_path: str) -> str:
        """Describe the image for the tool result: format, size, any scaling."""
        width, height = self.original_size
        parts = [f"Image {display_path}: {self.source_format}, {width}x{height}"]
        if self.sent_size != self.original_size:
            parts.append(f"scaled to {self.sent_size[0]}x{self.sent_size[1]} for viewing")
        if self.frames > 1:
            parts.append(f"animated with {self.frames} frames, showing the first")
        return ", ".join(parts) + ". The image is attached for you to look at."


def _encode(image: Image.Image, has_alpha: bool) -> tuple[bytes, str]:
    """Encode as PNG, or as JPEG when an opaque PNG would be needlessly large."""
    png = io.BytesIO()
    image.save(png, "PNG", optimize=True)
    if has_alpha or png.tell() <= _PNG_BUDGET_BYTES:
        return png.getvalue(), "image/png"
    jpeg = io.BytesIO()
    image.save(jpeg, "JPEG", quality=90)
    return jpeg.getvalue(), "image/jpeg"


def prepare_image(path: Path, max_dimension: int = 2048, detail: Detail = "auto") -> PreparedImage:
    """Decode, orient, downscale and re-encode `path` for the model."""
    if path.suffix.lower() == ".svg":
        raise ImageError(
            f"{path.name} is an SVG — vector XML rather than pixels. Read it with read_file."
        )
    try:
        with Image.open(path) as source:
            source_format = source.format or path.suffix.lstrip(".").upper() or "unknown"
            original_size = source.size
            frames = getattr(source, "n_frames", 1)
            frame = ImageOps.exif_transpose(source)
            has_alpha = frame.mode in ("RGBA", "LA", "PA") or (
                frame.mode == "P" and "transparency" in frame.info
            )
            frame = frame.convert("RGBA" if has_alpha else "RGB")
            frame.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            data, media_type = _encode(frame, has_alpha)
            sent_size = frame.size
    except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ImageError(f"{path.name} is not an image that can be decoded: {exc}") from exc
    except OSError as exc:
        raise ImageError(f"Could not decode {path.name}: {exc}") from exc

    return PreparedImage(
        attachment=ImageAttachment(
            media_type=media_type,
            data=base64.b64encode(data).decode("ascii"),
            label=path.name,
            detail=detail,
        ),
        source_format=source_format,
        original_size=original_size,
        sent_size=sent_size,
        frames=frames,
    )


__all__ = ["RASTER_EXTENSIONS", "Detail", "ImageError", "PreparedImage", "prepare_image"]
