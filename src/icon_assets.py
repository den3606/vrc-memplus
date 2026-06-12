"""Generate VRCMem+ application icon assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from .paths import PROJECT_ROOT

ASSETS = PROJECT_ROOT / "assets"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BG = "#1a1a1a"
BLOCK_BACK = (42, 74, 110, 140)
BLOCK_MID = (54, 120, 184, 255)
BLOCK_FRONT = (74, 154, 232, 255)
ACCENT = "#3b8ed0"
PLUS = "#ffffff"


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size / 256.0

    def s(value: float) -> int:
        return int(round(value * scale))

    radius = max(2, s(52))
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BG)

    for x1, y1, x2, y2, color in (
        (48, 62, 180, 100, BLOCK_BACK),
        (58, 92, 190, 130, BLOCK_MID),
        (68, 122, 200, 160, BLOCK_FRONT),
    ):
        draw.rounded_rectangle(
            (s(x1), s(y1), s(x2), s(y2)),
            radius=max(2, s(8)),
            fill=color,
        )

    cx, cy, r = s(190), s(176), max(2, s(30))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    bar_w, bar_h = max(2, s(28)), max(2, s(16))
    draw.rounded_rectangle(
        (cx - bar_w // 2, cy - bar_h // 2, cx + bar_w // 2, cy + bar_h // 2),
        radius=max(1, s(3)),
        fill=PLUS,
    )
    vert_w, vert_h = max(2, s(16)), max(2, s(28))
    draw.rounded_rectangle(
        (cx - vert_w // 2, cy - vert_h // 2, cx + vert_w // 2, cy + vert_h // 2),
        radius=max(1, s(3)),
        fill=PLUS,
    )
    return img


def ensure_icon_assets() -> None:
    ico_path = ASSETS / "icon.ico"
    if ico_path.exists():
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon(256)
    master.save(ASSETS / "icon.png")
    master.save(
        ico_path,
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )


def generate_icon_assets() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_icon(256)
    master.save(ASSETS / "icon.png")
    master.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(size, size) for size in SIZES],
    )
