"""Convert regular photos into VRChat Print format."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont, ImageOps

ORIG_W, ORIG_H = 2048, 1440
SIDE_BORDER, TOP_BORDER, BOTTOM_TEXT = 64, 69, 291
INNER_W, INNER_H = ORIG_W - 2 * SIDE_BORDER, ORIG_H - TOP_BORDER - BOTTOM_TEXT

SCALE = 1080 / 1920.0
SIDE_SCALED = int(round(SIDE_BORDER * SCALE))
TOP_SCALED = int(round(TOP_BORDER * SCALE))
BOTTOM_TEXT_SCALED = int(round(BOTTOM_TEXT * SCALE))

PORT_W = 1080 + 2 * SIDE_SCALED
PORT_H = 1920 + TOP_SCALED + BOTTOM_TEXT_SCALED
LANDSCAPE_UPLOAD_SIZE = (ORIG_W, ORIG_H)
PORTRAIT_UPLOAD_SIZE = (ORIG_H, ORIG_W)
PORTRAIT_FILE_SIZE = (PORT_W, PORT_H)
VALID_PRINT_SIZES = frozenset((LANDSCAPE_UPLOAD_SIZE, PORTRAIT_UPLOAD_SIZE, PORTRAIT_FILE_SIZE))

Orientation = Literal["landscape", "portrait"]
FrameMode = Literal["light", "dark"]
CropMode = Literal["cover", "contain"]


class OrientationChoice(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


@dataclass
class PrintOptions:
    orientation: Orientation = "landscape"
    frame_mode: FrameMode = "light"
    note: str = ""
    author_name: str = ""
    world_name: str = ""
    timestamp: datetime | None = None
    crop_mode: CropMode = "cover"


def _inner_size(orientation: Orientation) -> tuple[int, int]:
    if orientation == "landscape":
        return INNER_W, INNER_H
    return 1080, 1920


def _canvas_size(orientation: Orientation) -> tuple[int, int]:
    if orientation == "landscape":
        return ORIG_W, ORIG_H
    return PORT_W, PORT_H


def _frame_color(frame_mode: FrameMode) -> tuple[int, int, int]:
    return (0, 0, 0) if frame_mode == "dark" else (255, 255, 255)


def _text_color(frame_mode: FrameMode) -> tuple[int, int, int]:
    return (255, 255, 255) if frame_mode == "dark" else (0, 0, 0)


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                ("C:/Windows/Fonts/meiryob.ttc", 0),
                ("C:/Windows/Fonts/msgothic.ttc", 0),
                ("C:/Windows/Fonts/segoeuib.ttf", None),
            ]
        )
    else:
        candidates.extend(
            [
                ("C:/Windows/Fonts/meiryo.ttc", 0),
                ("C:/Windows/Fonts/msgothic.ttc", 0),
                ("C:/Windows/Fonts/segoeui.ttf", None),
            ]
        )
    for path, index in candidates:
        try:
            if index is None:
                return ImageFont.truetype(path, size=size)
            return ImageFont.truetype(path, size=size, index=index)
        except OSError:
            continue
    return ImageFont.load_default()


def load_source_image(input_path: str | Path) -> Image.Image:
    input_path = Path(input_path)
    with Image.open(input_path) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            alpha = image.split()[-1] if image.mode in ("RGBA", "LA") else None
            rgb = image.convert("RGB")
            if alpha is not None:
                background.paste(rgb, mask=alpha)
            else:
                background.paste(rgb)
            return background.copy()
        return image.convert("RGB")


def _fit_image(image: Image.Image, target_w: int, target_h: int, crop_mode: CropMode) -> Image.Image:
    image = image.convert("RGB")
    src_w, src_h = image.size
    if src_w == 0 or src_h == 0:
        raise ValueError("Image has zero width or height")

    if crop_mode == "contain":
        fitted = ImageOps.contain(image, (target_w, target_h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        offset = ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2)
        canvas.paste(fitted, offset)
        return canvas

    return ImageOps.fit(image, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def upload_canvas_size(orientation: Orientation) -> tuple[int, int]:
    if orientation == "landscape":
        return LANDSCAPE_UPLOAD_SIZE
    return PORTRAIT_UPLOAD_SIZE


def is_valid_print_size(size: tuple[int, int]) -> bool:
    return size in VALID_PRINT_SIZES


def can_passthrough_upload(size: tuple[int, int], orientation: Orientation) -> bool:
    if size == upload_canvas_size(orientation):
        return True
    if orientation == "portrait" and size == PORTRAIT_FILE_SIZE:
        return True
    return size == LANDSCAPE_UPLOAD_SIZE and orientation == "landscape"


def assert_upload_image(image: Image.Image, orientation: Orientation) -> None:
    expected = upload_canvas_size(orientation)
    if image.size != expected:
        raise ValueError(
            f"Print 画像サイズが不正です ({image.size[0]}x{image.size[1]})。"
            f"必要サイズ: {expected[0]}x{expected[1]}"
        )


def _draw_bottom_bar(
    draw: ImageDraw.ImageDraw,
    canvas_w: int,
    canvas_h: int,
    bottom_h: int,
    options: PrintOptions,
) -> None:
    text_color = _text_color(options.frame_mode)
    note_font = _load_font(42, bold=False)
    meta_font = _load_font(30, bold=False)
    padding_x = 48
    top_y = canvas_h - bottom_h
    y_note = top_y + 24

    note = options.note.strip()
    if note:
        draw.text((padding_x, y_note), note, fill=text_color, font=note_font)

    author = options.author_name.strip()
    world = options.world_name.strip()
    ts = options.timestamp or datetime.now()
    date_text = ts.strftime("%Y/%m/%d")

    meta_y = top_y + bottom_h - 52
    if author:
        draw.text((padding_x, meta_y), author, fill=text_color, font=meta_font)

    right_parts = [date_text]
    if world:
        right_parts.append(world)
    right_text = "  ".join(right_parts)
    bbox = draw.textbbox((0, 0), right_text, font=meta_font)
    right_w = bbox[2] - bbox[0]
    draw.text((canvas_w - padding_x - right_w, meta_y), right_text, fill=text_color, font=meta_font)


def convert_to_print(image: Image.Image, options: PrintOptions) -> Image.Image:
    orientation = options.orientation
    canvas_w, canvas_h = _canvas_size(orientation)
    inner_w, inner_h = _inner_size(orientation)
    frame_color = _frame_color(options.frame_mode)

    if orientation == "landscape":
        side, top, bottom_h = SIDE_BORDER, TOP_BORDER, BOTTOM_TEXT
    else:
        side, top, bottom_h = SIDE_SCALED, TOP_SCALED, BOTTOM_TEXT_SCALED

    photo = _fit_image(image, inner_w, inner_h, options.crop_mode)
    canvas = Image.new("RGB", (canvas_w, canvas_h), frame_color)
    canvas.paste(photo, (side, top))

    draw = ImageDraw.Draw(canvas)
    _draw_bottom_bar(draw, canvas_w, canvas_h, bottom_h, options)
    return canvas


def detect_orientation(image: Image.Image) -> Orientation:
    w, h = image.size
    if (w, h) == LANDSCAPE_UPLOAD_SIZE:
        return "landscape"
    if (w, h) in (PORTRAIT_UPLOAD_SIZE, PORTRAIT_FILE_SIZE):
        return "portrait"
    return "landscape" if w >= h else "portrait"


def detect_frame_mode(image: Image.Image) -> FrameMode:
    r, g, b = image.convert("RGB").getpixel((1, 1))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "light" if lum > 127 else "dark"


def extract_photo_from_print(image: Image.Image) -> tuple[Image.Image, Orientation]:
    orientation = detect_orientation(image)
    if orientation == "landscape":
        box = (SIDE_BORDER, TOP_BORDER, SIDE_BORDER + INNER_W, TOP_BORDER + INNER_H)
    else:
        box = (SIDE_SCALED, TOP_SCALED, SIDE_SCALED + 1080, TOP_SCALED + 1920)
    return image.crop(box), orientation


def rebuild_print_with_note(
    print_image: Image.Image,
    note: str,
    author_name: str = "",
    world_name: str = "",
    timestamp: datetime | None = None,
) -> Image.Image:
    photo, orientation = extract_photo_from_print(print_image)
    options = PrintOptions(
        orientation=orientation,
        frame_mode=detect_frame_mode(print_image),
        note=note,
        author_name=author_name,
        world_name=world_name,
        timestamp=timestamp,
        crop_mode="cover",
    )
    return convert_to_print(photo, options)


def resize_to_print_canvas(
    image: Image.Image,
    orientation: Orientation,
    crop_mode: CropMode = "cover",
) -> Image.Image:
    canvas_w, canvas_h = _canvas_size(orientation)
    result = _fit_image(image, canvas_w, canvas_h, crop_mode)
    if result.size != (canvas_w, canvas_h):
        result = result.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    return result


def save_png_without_metadata(image: Image.Image, output_path: str | Path) -> Path:
    """Re-encode PNG without ancillary chunks (VRChat vrc:WorldDisplayName etc.)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
    return output_path


def resize_to_upload_canvas(
    image: Image.Image,
    orientation: Orientation,
    crop_mode: CropMode = "cover",
) -> Image.Image:
    canvas_w, canvas_h = upload_canvas_size(orientation)
    result = _fit_image(image, canvas_w, canvas_h, crop_mode)
    if result.size != (canvas_w, canvas_h):
        result = result.resize((canvas_w, canvas_h), Image.Resampling.LANCZOS)
    return result


def prepare_print_for_upload(
    input_path: str | Path,
    output_path: str | Path,
    orientation: Orientation = "landscape",
    crop_mode: CropMode = "cover",
) -> tuple[Path, Orientation]:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        raise FileNotFoundError(f"画像が見つかりません: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = load_source_image(input_path)
    upload_orientation = orientation

    if can_passthrough_upload(image.size, upload_orientation):
        # Re-save instead of copying so embedded world metadata does not override
        # the worldName field sent in the upload form.
        save_png_without_metadata(image, output_path)
        return output_path, detect_orientation(image)

    result = resize_to_upload_canvas(image, upload_orientation, crop_mode)
    assert_upload_image(result, upload_orientation)
    save_png_without_metadata(result, output_path)
    return output_path, upload_orientation


def resize_file_to_print_canvas(
    input_path: str | Path,
    output_path: str | Path,
    orientation: Orientation = "landscape",
    crop_mode: CropMode = "cover",
) -> Path:
    prepared, _orientation = prepare_print_for_upload(
        input_path,
        output_path,
        orientation=orientation,
        crop_mode=crop_mode,
    )
    return prepared


def convert_file(input_path: str | Path, output_path: str | Path, options: PrintOptions) -> Path:
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        raise FileNotFoundError(f"画像が見つかりません: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image = load_source_image(input_path)
    result = convert_to_print(image, options)
    result.save(output_path, format="PNG")
    return output_path


def convert_to_bytes(image: Image.Image, options: PrintOptions) -> bytes:
    result = convert_to_print(image, options)
    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return buffer.getvalue()


def batch_convert(
    input_paths: list[str | Path],
    output_dir: str | Path,
    options: PrintOptions,
) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for input_path in input_paths:
        src = Path(input_path)
        out = output_dir / f"{src.stem}_print.png"
        outputs.append(convert_file(src, out, options))
    return outputs
