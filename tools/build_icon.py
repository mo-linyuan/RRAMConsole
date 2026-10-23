"""Build the editable chip icon and PNG/ICO assets with the standard library.

Run from the project root: python -m tools.build_icon
"""

from pathlib import Path
import math
import struct
import zlib


ASSETS = Path(__file__).resolve().parents[1] / "i1003" / "ui" / "assets"
BLUE = (37, 99, 235)
WHITE = (255, 255, 255)
PINS = (59, 130, 246)


def rounded(x, y, left, top, right, bottom, radius):
    if not (left <= x <= right and top <= y <= bottom):
        return False
    cx = min(right - radius, max(left + radius, x))
    cy = min(bottom - radius, max(top + radius, y))
    return math.hypot(x - cx, y - cy) <= radius


def pixel(x, y):
    color = None
    for p in (80, 112, 144, 176):
        if any(rounded(x, y, *bounds, 5) for bounds in (
                (p - 6, 28, p + 6, 62), (p - 6, 194, p + 6, 228),
                (28, p - 6, 62, p + 6), (194, p - 6, 228, p + 6))):
            color = PINS
            break
    if rounded(x, y, 56, 56, 200, 200, 24):
        color = BLUE
    if rounded(x, y, 72, 72, 184, 184, 12):
        color = WHITE
        for row in range(3):
            for col in range(3):
                a, b = 88 + col * 32, 88 + row * 32
                if rounded(x, y, a, b, a + 16, b + 16, 3):
                    color = BLUE
    return color + (255,) if color else (0, 0, 0, 0)


def png(size):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            samples = [pixel((x + (sx + .5) / 3) * 256 / size,
                             (y + (sy + .5) / 3) * 256 / size) for sy in range(3) for sx in range(3)]
            alpha = sum(p[3] for p in samples)
            rgb = [round(sum(p[c] * p[3] for p in samples) / alpha) if alpha else 0 for c in range(3)]
            raw.extend(rgb + [round(alpha / 9)])

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">',
           '<title>RRAM Chip Console</title>']
    for p in (80, 112, 144, 176):
        for x, y, w, h in ((p - 6, 28, 12, 34), (p - 6, 194, 12, 34), (28, p - 6, 34, 12), (194, p - 6, 34, 12)):
            svg.append('<rect x="{}" y="{}" width="{}" height="{}" rx="5" fill="#3b82f6"/>'.format(x, y, w, h))
    svg.extend(['<rect x="56" y="56" width="144" height="144" rx="24" fill="#2563eb"/>',
                '<rect x="72" y="72" width="112" height="112" rx="12" fill="white"/>'])
    for row in range(3):
        for col in range(3):
            svg.append('<rect x="{}" y="{}" width="16" height="16" rx="3" fill="#2563eb"/>'.format(88 + col * 32, 88 + row * 32))
    (ASSETS / "app.svg").write_text("\n".join(svg + ["</svg>"]) + "\n", encoding="utf-8")
    sizes = (16, 24, 32, 48, 64, 128, 256)
    images = [png(size) for size in sizes]
    entries, offset = [], 6 + 16 * len(sizes)
    dibs = []
    for size, data in zip(sizes, images):
        dib = icon_dib(size, data)
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(dib), offset))
        offset += len(dib)
        dibs.append(dib)
        (ASSETS / "app-{}.png".format(size)).write_bytes(data)
    (ASSETS / "app.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(entries) + b"".join(dibs))
    print("Built SVG, ICO and {} PNG sizes in {}".format(len(sizes), ASSETS))


def icon_dib(size, data):
    """Uncompressed Windows ICO frames, including the legacy transparency mask.

    Some Tk/Windows icon loaders do not handle PNG-compressed ICO frames.
    The PNG files above are ours and always use PNG filter 0.
    """
    compressed, pos = bytearray(), 8
    while pos < len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        if data[pos + 4:pos + 8] == b"IDAT":
            compressed.extend(data[pos + 8:pos + 8 + length])
        pos += length + 12
    raw = zlib.decompress(compressed)
    pixels, mask = bytearray(), bytearray()
    mask_stride = ((size + 31) // 32) * 4
    for y in reversed(range(size)):
        row = raw[y * (1 + size * 4) + 1:(y + 1) * (1 + size * 4)]
        mask_row = bytearray(mask_stride)
        for x in range(size):
            r, g, b, a = row[x * 4:x * 4 + 4]
            pixels.extend((b, g, r, a))
            if a == 0:
                mask_row[x // 8] |= 1 << (7 - x % 8)
        mask.extend(mask_row)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    return header + pixels + mask


if __name__ == "__main__":
    main()
