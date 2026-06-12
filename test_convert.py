"""Quick conversion test. Run: python test_convert.py path/to/image.jpg"""

from __future__ import annotations

import sys
from pathlib import Path

from src.vrcprint_converter import PrintOptions, convert_file


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python test_convert.py <image-path>")
        sys.exit(1)

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)

    out = src.with_name(f"{src.stem}_vrcprint.png")
    options = PrintOptions(note="test", author_name="TestUser", world_name="TestWorld")
    result = convert_file(src, out, options)
    print(f"OK: {result} ({result.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
