"""Persist app settings and auth cookies."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

_LEGACY_APP_DIR = "VRCPrintDesktop"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / "VRCMemPlus"
    legacy = Path(base) / _LEGACY_APP_DIR
    if not path.exists() and legacy.exists():
        shutil.copytree(legacy, path)
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    username: str = ""
    user_agent: str = "VRCMemPlus/1.0.0"
    contact_email: str = ""
    default_orientation: str = "landscape"
    default_crop_mode: str = "cover"
    default_note: str = ""
    default_world_name: str = "local"
    default_set_icon_on_upload: bool = True
    output_dir: str = ""
    auth_cookie: str = ""
    user_id: str = ""
    display_name: str = ""

    @classmethod
    def load(cls) -> "AppSettings":
        path = app_data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return cls()

    def save(self) -> None:
        path = app_data_dir() / "settings.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
