"""Generate WavePilot SDR PNG and ICO icons from the vector brand."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "wavepilot" / "assets"
SOURCE = ASSET_DIR / "wavepilot-icon.svg"
PNG = ASSET_DIR / "wavepilot-icon.png"
ICO = ASSET_DIR / "wavepilot-icon.ico"
DOCS_FAVICON = ROOT / "docs" / "favicon.svg"
STATIC_FAVICON = ROOT / "wavepilot" / "static" / "favicon.svg"


def render_png(size):
    renderer = QSvgRenderer(str(SOURCE))
    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    return image


def write_ico(images, target):
    png_blobs = []
    for size, image in images:
        temp = ASSET_DIR / f".wavepilot-{size}.png"
        image.save(str(temp), "PNG")
        png_blobs.append((size, temp.read_bytes()))
        temp.unlink()

    header = struct.pack("<HHH", 0, 1, len(png_blobs))
    entries = []
    offset = 6 + len(png_blobs) * 16
    payload = bytearray()
    for size, blob in png_blobs:
        width = 0 if size >= 256 else size
        height = 0 if size >= 256 else size
        entries.append(struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset))
        payload.extend(blob)
        offset += len(blob)
    target.write_bytes(header + b"".join(entries) + bytes(payload))


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    large = render_png(512)
    large.save(str(PNG), "PNG")
    write_ico([(16, render_png(16)), (32, render_png(32)), (48, render_png(48)), (64, render_png(64)), (128, render_png(128)), (256, render_png(256))], ICO)
    DOCS_FAVICON.write_text(SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    STATIC_FAVICON.write_text(SOURCE.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Generated {PNG}")
    print(f"Generated {ICO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
