"""Generate app/assets/miniai_logo.png and multi-size miniai.ico."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS = PROJECT_ROOT / "app" / "assets"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(size):
        for x in range(size):
            nx = x / max(size - 1, 1)
            ny = y / max(size - 1, 1)
            px, py = min(nx, 1 - nx), min(ny, 1 - ny)
            r = 0.22
            inside = True
            if px < r and py < r:
                dx, dy = r - px, r - py
                inside = (dx * dx + dy * dy) <= r * r
            if not inside:
                continue
            t = (nx + ny) / 2
            if t < 0.55:
                u = t / 0.55
                cr = int(0x8A + (0x6B - 0x8A) * u)
                cg = int(0xA4 + (0x7C - 0xA4) * u)
                cb = 0xFF
            else:
                u = (t - 0.55) / 0.45
                cr = int(0x6B + (0x4F - 0x6B) * u)
                cg = int(0x7C + (0xD1 - 0x7C) * u)
                cb = int(0xFF + (0xC5 - 0xFF) * u)
            img.putpixel((x, y), (cr, cg, cb, 255))
    try:
        font = ImageFont.truetype(
            r"C:\Windows\Fonts\segoeuib.ttf", max(10, int(size * 0.55))
        )
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), "M", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - size * 0.02),
        "M",
        font=font,
        fill=(255, 255, 255, 255),
    )
    return img


def _png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def write_multi_ico(path: Path, images: list[Image.Image]) -> None:
    """Write an ICO containing PNG-compressed images (Vista+)."""
    pngs = [_png_bytes(im) for im in images]
    count = len(pngs)
    offset = 6 + 16 * count
    entries = []
    blobs = b""
    for im, png in zip(images, pngs):
        w, h = im.size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if w >= 256 else w,
                0 if h >= 256 else h,
                0,
                0,
                1,
                32,
                len(png),
                offset + len(blobs),
            )
        )
        blobs += png
    header = struct.pack("<HHH", 0, 1, count)
    path.write_bytes(header + b"".join(entries) + blobs)


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    master = draw_logo(512)
    logo = ASSETS / "miniai_logo.png"
    master.save(logo)
    images = [draw_logo(s) for s in SIZES]
    ico = ASSETS / "miniai.ico"
    write_multi_ico(ico, images)
    # Keep design copy for older shortcut paths.
    design = PROJECT_ROOT / "app" / "design" / "miniai.ico"
    design.write_bytes(ico.read_bytes())
    print(f"LOGO={logo} bytes={logo.stat().st_size}")
    print(f"ICO={ico} bytes={ico.stat().st_size} sizes={SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
