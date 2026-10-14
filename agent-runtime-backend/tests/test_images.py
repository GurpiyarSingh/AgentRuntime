from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from agent_runtime.files.images import ImageError, prepare_image


def _decode(data: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data)))


@pytest.mark.parametrize("extension", ["png", "jpg", "gif", "webp", "bmp", "tiff", "ico"])
def test_common_formats_become_png_or_jpeg(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"image.{extension}"
    Image.new("RGB", (64, 32), "red").save(path)

    prepared = prepare_image(path)

    assert prepared.attachment.media_type in ("image/png", "image/jpeg")
    assert prepared.original_size == (64, 32) or extension == "ico"
    assert _decode(prepared.attachment.data).format in ("PNG", "JPEG")
    assert prepared.attachment.label == path.name


def test_large_images_are_scaled_to_fit(tmp_path: Path) -> None:
    path = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), "blue").save(path)

    prepared = prepare_image(path, max_dimension=1000)

    assert prepared.original_size == (4000, 1000)
    assert prepared.sent_size == (1000, 250)
    assert _decode(prepared.attachment.data).size == (1000, 250)
    assert "scaled to 1000x250" in prepared.summary("big.png")


def test_transparency_is_kept_as_png(tmp_path: Path) -> None:
    path = tmp_path / "logo.png"
    Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(path)
    prepared = prepare_image(path)
    assert prepared.attachment.media_type == "image/png"
    assert _decode(prepared.attachment.data).mode == "RGBA"


def test_animated_gif_reports_frames(tmp_path: Path) -> None:
    path = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (8, 8), color) for color in ("red", "green", "blue")]
    frames[0].save(path, save_all=True, append_images=frames[1:])

    prepared = prepare_image(path)

    assert prepared.frames == 3
    assert "3 frames" in prepared.summary("anim.gif")


def test_detail_is_passed_through(tmp_path: Path) -> None:
    path = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(path)
    assert prepare_image(path, detail="high").attachment.detail == "high"


def test_non_images_raise_image_error(tmp_path: Path) -> None:
    path = tmp_path / "fake.png"
    path.write_text("definitely not a png")
    with pytest.raises(ImageError):
        prepare_image(path)


def test_svg_points_to_read_file(tmp_path: Path) -> None:
    path = tmp_path / "icon.svg"
    path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with pytest.raises(ImageError, match="read_file"):
        prepare_image(path)
