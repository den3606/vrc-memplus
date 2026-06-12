"""Prepare images for VRChat Photo Gallery upload."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

MAX_DIMENSION = 2047
MIN_DIMENSION = 64
MAX_BYTES = 10 * 1024 * 1024


def validate_gallery_dimensions(width: int, height: int) -> None:
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ValueError(f"画像が小さすぎます ({MIN_DIMENSION}x{MIN_DIMENSION} 以上が必要)")
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ValueError(
            f"画像が大きすぎます ({width}x{height})。"
            f"各辺を {MAX_DIMENSION}px 以下にしてください"
        )


def prepare_gallery_image(input_path: str | Path, output_path: str | Path) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if max(image.size) > MAX_DIMENSION:
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        validate_gallery_dimensions(image.width, image.height)
        image.save(output_path, format="PNG", optimize=True)

    size = output_path.stat().st_size
    if size > MAX_BYTES:
        with Image.open(output_path) as image:
            scale = (MAX_BYTES / size) ** 0.5
            new_size = (max(MIN_DIMENSION, int(image.width * scale)), max(MIN_DIMENSION, int(image.height * scale)))
            resized = image.resize(new_size, Image.Resampling.LANCZOS)
            resized.save(output_path, format="PNG", optimize=True)

    if output_path.stat().st_size > MAX_BYTES:
        raise ValueError("画像を 10MB 以下に圧縮できませんでした")

    with Image.open(output_path) as saved:
        validate_gallery_dimensions(saved.width, saved.height)

    return output_path
