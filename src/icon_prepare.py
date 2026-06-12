"""Prepare images for VRChat user icon upload."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

MAX_DIMENSION = 2048
MIN_DIMENSION = 64
MAX_BYTES = 10 * 1024 * 1024


def validate_icon_dimensions(width: int, height: int) -> None:
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        raise ValueError(f"画像が小さすぎます ({MIN_DIMENSION}x{MIN_DIMENSION} 以上が必要)")
    if width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ValueError(
            f"画像が大きすぎます ({width}x{height})。"
            f"各辺を {MAX_DIMENSION}px 以下にしてください"
        )
    if width != height:
        raise ValueError(f"正方形ではありません ({width}x{height})")


def _square_crop(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def _fit_square(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    square = _square_crop(image)
    if square.width > MAX_DIMENSION:
        square = square.resize((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
    validate_icon_dimensions(square.width, square.height)
    return square


def _save_png(image: Image.Image, output_path: Path) -> None:
    image.save(output_path, format="PNG", optimize=True)


def prepare_icon_image(input_path: str | Path, output_path: str | Path) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as image:
        result = _fit_square(image)
        _save_png(result, output_path)

    size = output_path.stat().st_size
    if size > MAX_BYTES:
        with Image.open(output_path) as image:
            scale = (MAX_BYTES / size) ** 0.5
            new_side = max(MIN_DIMENSION, int(image.width * scale))
            resized = image.resize((new_side, new_side), Image.Resampling.LANCZOS)
            _save_png(resized, output_path)

    if output_path.stat().st_size > MAX_BYTES:
        raise ValueError("画像を 10MB 以下に圧縮できませんでした")

    with Image.open(output_path) as saved:
        validate_icon_dimensions(saved.width, saved.height)

    return output_path
