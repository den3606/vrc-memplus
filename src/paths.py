"""Resolve bundled resource paths for dev and PyInstaller builds."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    else:
        base = PROJECT_ROOT
    return base.joinpath(*parts)


def app_icon_path() -> Path:
    return resource_path("assets", "icon.ico")
