"""Write a simple MiniAI 'M' logo .ico (no external deps beyond stdlib+struct)."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path


def _png_rgba(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter none
        for x in range(size):
            # Rounded-rect gradient similar to design logo
            nx, ny = x / (size - 1), y / (size - 1)
            # corner radius ~ 0.22
            r = 0.22
            # distance outside rounded rect
            px = min(nx, 1 - nx)
            py = min(ny, 1 - ny)
            inside = True
            if px < r and py < r:
                dx, dy = r - px, r - py
                inside = (dx * dx + dy * dy) <= r * r
            if not inside:
                row.extend((0, 0, 0, 0))
                continue
            # gradient 135deg: #8AA4FF -> #6B7CFF -> #4FD1C5
            t = (nx + ny) / 2
            if t < 0.55:
                u = t / 0.55
                cr = int(0x8A + (0x6B - 0x8A) * u)
                cg = int(0xA4 + (0x7C - 0xA4) * u)
                cb = int(0xFF + (0xFF - 0xFF) * u)
            else:
                u = (t - 0.55) / 0.45
                cr = int(0x6B + (0x4F - 0x6B) * u)
                cg = int(0x7C + (0xD1 - 0x7C) * u)
                cb = int(0xFF + (0xC5 - 0xFF) * u)
            # Draw a simple "M" in dark ink
            ink = False
            # normalized coords in letter box
            lx = (nx - 0.22) / 0.56
            ly = (ny - 0.18) / 0.64
            if 0 <= lx <= 1 and 0 <= ly <= 1:
                # left stem, right stem, V peaks
                stem = 0.16
                if lx <= stem or lx >= 1 - stem:
                    ink = True
                else:
                    # two diagonals meeting at center top-ish
                    mid = 0.5
                    d1 = abs((ly) - (lx / mid) * 0.55)
                    d2 = abs((ly) - ((1 - lx) / mid) * 0.55)
                    if lx <= mid and d1 < 0.14 and ly < 0.7:
                        ink = True
                    if lx >= mid and d2 < 0.14 and ly < 0.7:
                        ink = True
            if ink:
                row.extend((0x0D, 0x12, 0x20, 255))
            else:
                row.extend((cr, cg, cb, 255))
        rows.append(bytes(row))
    raw = b"".join(rows)
    compressed = zlib.compress(raw, 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def write_ico(path: Path, size: int = 32) -> None:
    png = _png_rgba(size)
    # ICO with one PNG image (Vista+)
    header = struct.pack("<HHH", 0, 1, 1)
    # width/height 0 means 256; for 32 use 32
    entry = struct.pack(
        "<BBBBHHII",
        size if size < 256 else 0,
        size if size < 256 else 0,
        0,
        0,
        1,
        32,
        len(png),
        22,  # offset after header+entry
    )
    path.write_bytes(header + entry + png)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "app/design/miniai.ico")
    out.parent.mkdir(parents=True, exist_ok=True)
    write_ico(out)
    print(f"ICO={out} bytes={out.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
