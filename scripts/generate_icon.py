"""Generate Windows .ico from the VRCMem+ block icon design."""

from __future__ import annotations

from src.icon_assets import generate_icon_assets


def main() -> None:
    generate_icon_assets()
    print("Wrote assets/icon.ico and assets/icon.png")


if __name__ == "__main__":
    main()
