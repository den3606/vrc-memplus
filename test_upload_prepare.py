"""Validate upload image preparation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from src.gallery_prepare import prepare_gallery_image, validate_gallery_dimensions
from src.print_converter import (
    LANDSCAPE_UPLOAD_SIZE,
    ORIG_H,
    ORIG_W,
    PORTRAIT_UPLOAD_SIZE,
    PORT_H,
    PORT_W,
    is_valid_print_size,
    prepare_print_for_upload,
)


def test_print_resize_from_1920x1080() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.png"
        out = Path(tmp) / "print.png"
        Image.new("RGB", (1920, 1080), (40, 80, 120)).save(src)

        prepared, orientation = prepare_print_for_upload(src, out, orientation="landscape", crop_mode="cover")
        with Image.open(prepared) as image:
            assert image.size == LANDSCAPE_UPLOAD_SIZE, image.size
            assert orientation == "landscape"
        assert is_valid_print_size(LANDSCAPE_UPLOAD_SIZE)


def test_print_resize_portrait_from_1920x1080() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.png"
        out = Path(tmp) / "print.png"
        Image.new("RGB", (1920, 1080), (40, 80, 120)).save(src)

        prepared, orientation = prepare_print_for_upload(src, out, orientation="portrait", crop_mode="cover")
        with Image.open(prepared) as image:
            assert image.size == PORTRAIT_UPLOAD_SIZE, image.size
            assert max(image.size) <= 2048
            assert orientation == "portrait"


def test_gallery_keeps_1920x1080() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "source.png"
        out = Path(tmp) / "gallery.png"
        Image.new("RGB", (1920, 1080), (40, 80, 120)).save(src)

        prepare_gallery_image(src, out)
        with Image.open(out) as image:
            validate_gallery_dimensions(image.width, image.height)
            assert image.size == (1920, 1080)


def test_valid_print_passthrough() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "print.png"
        out = Path(tmp) / "copy.png"
        Image.new("RGB", (PORT_W, PORT_H), (255, 255, 255)).save(src)

        prepared, orientation = prepare_print_for_upload(src, out, orientation="landscape", crop_mode="cover")
        with Image.open(prepared) as image:
            assert image.size == (PORT_W, PORT_H)
            assert orientation == "portrait"


def main() -> None:
    test_print_resize_from_1920x1080()
    test_print_resize_portrait_from_1920x1080()
    test_gallery_keeps_1920x1080()
    test_valid_print_passthrough()
    print("OK")


if __name__ == "__main__":
    main()
