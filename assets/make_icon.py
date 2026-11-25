#!/usr/bin/env python3
"""Generate the Battery Notifier icon set.

The artwork is drawn in code so the icon stays reproducible and reviewable,
rather than being an opaque binary blob in the repository.

    python assets/make_icon.py            # write the .ico + .png + preview
    python assets/make_icon.py --check    # fail if the files are out of date

Outputs (next to this script):

    battery-notifier.ico    multi-resolution Windows icon (16-256 px)
    battery-notifier.png    256 px PNG, for docs / future macOS artwork
    icon-preview.png        contact sheet showing every size

Sizes up to 64 px are stored as uncompressed 32-bit DIBs and 128/256 px as
PNG, which is the combination Windows Explorer handles best: the small
frames stay crisp in the taskbar and shortcut lists, while the large frames
stay small on disk.

Requires: pip install Pillow
"""

from __future__ import annotations

import argparse
import io
import os
import struct
import sys

# Palette. The greens deliberately separate: a dark outline, a dark empty
# chamber, and a bright charged chamber, so the fill level stays readable
# even at 16 px.
BORDER = (20, 92, 42, 255)          # outline + terminal nub
EMPTY = (17, 56, 32, 255)           # uncharged part of the chamber
LEVEL = (63, 185, 80, 255)          # charged part of the chamber
WHITE = (255, 255, 255, 255)        # lightning bolt
SHADOW = (0, 0, 0, 40)              # soft drop shadow behind the shell

# Sizes baked into the .ico, smallest first.
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
# Sizes rendered as PNG inside the .ico; the rest are DIB.
PNG_SIZES = (128, 256)

# Supersampling factor: draw big, then downscale for clean anti-aliased edges.
SS = 4

HERE = os.path.dirname(os.path.abspath(__file__))
ICO_PATH = os.path.join(HERE, "battery-notifier.ico")
PNG_PATH = os.path.join(HERE, "battery-notifier.png")
PREVIEW_PATH = os.path.join(HERE, "icon-preview.png")


def _geometry(s: float) -> dict:
    """Battery geometry for a canvas of `s` pixels (fractions of the canvas)."""
    return {
        "body": (0.050 * s, 0.245 * s, 0.820 * s, 0.755 * s),
        # Nub is tucked *under* the body edge so the two read as one object.
        "nub": (0.790 * s, 0.400 * s, 0.965 * s, 0.600 * s),
        "nub_radius": 0.045 * s,
        "radius": 0.135 * s,
        "stroke": max(1.0, 0.055 * s),
        "pad": max(1.0, 0.115 * s),
        "level": 0.75,  # fraction of the chamber that is charged
    }


def _bolt(s: float) -> list:
    """A four-point lightning bolt centred in the battery body."""
    cx, cy, h = 0.425 * s, 0.500 * s, 0.190 * s
    w = h * 0.62
    return [
        (cx + w * 0.30, cy - h),
        (cx - w * 1.00, cy + h * 0.10),
        (cx - w * 0.10, cy + h * 0.10),
        (cx - w * 0.38, cy + h),
        (cx + w * 1.00, cy - h * 0.12),
        (cx + w * 0.06, cy - h * 0.12),
    ]


def _draw(size: int):
    """Render one icon frame at `size` px and return an RGBA Image."""
    from PIL import Image, ImageDraw

    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    g = _geometry(big)

    x0, y0, x1, y1 = g["body"]
    stroke = max(1, int(round(g["stroke"])))
    pad = g["pad"]

    # Terminal nub first: the shell is drawn over its inner edge, so the
    # outline joins up instead of leaving a gap.
    d.rounded_rectangle(list(g["nub"]), radius=g["nub_radius"], fill=BORDER)

    # Soft shadow lifts the shell off light AND dark taskbars.
    if size >= 24:
        sx, sy = 0.010 * big, 0.016 * big
        d.rounded_rectangle([x0 + sx, y0 + sy, x1 + sx, y1 + sy],
                            radius=g["radius"], fill=SHADOW)

    # Battery shell.
    d.rounded_rectangle([x0, y0, x1, y1], radius=g["radius"], fill=BORDER)

    # Inner chamber: uncharged portion, then the charged portion on top.
    # The two greens differ enough to read as a level at 16 px.
    cl, ct = x0 + stroke + pad * 0.55, y0 + stroke + pad * 0.55
    cr, cb = x1 - stroke - pad * 0.55, y1 - stroke - pad * 0.55
    d.rectangle([cl, ct, cr, cb], fill=EMPTY)

    level_w = (cr - cl) * g["level"]
    d.rectangle([cl, ct, cl + level_w, cb], fill=LEVEL)

    # Lightning bolt sits over the level.
    d.polygon(_bolt(big), fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def _dib_bytes(img) -> bytes:
    """Encode an RGBA image as a 32-bit bottom-up DIB (the ICO 'BMP' format).

    An icon DIB stores twice the height: the XOR (colour) bitmap followed by
    a 1-bit AND mask. The mask is all zeros because these icons are alpha
    blended, but it must still be present and 32-bit row padded.
    """
    w, h = img.size
    px = img.load()
    rows = []
    for y in range(h - 1, -1, -1):
        row = bytearray()
        for x in range(w):
            r, g, b, a = px[x, y]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)
    mask_stride = ((w + 31) // 32) * 4
    mask = b"\x00" * (mask_stride * h)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        w, h * 2,    # biWidth, biHeight (XOR + AND)
        1, 32,       # biPlanes, biBitCount
        0,           # biCompression (BI_RGB)
        len(xor) + len(mask),
        0, 0, 0, 0,  # ppm, clrUsed, clrImportant
    )
    return header + xor + mask


def _png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _ico_bytes(frames: dict) -> bytes:
    """Assemble a complete .ico container from {size: RGBA image}."""
    entries, payloads = [], []
    offset = 6 + 16 * len(frames)  # header + one 16-byte directory entry each

    for size in sorted(frames):
        img = frames[size]
        data = _png_bytes(img) if size in PNG_SIZES else _dib_bytes(img)
        entries.append(struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # width  (0 means 256)
            0 if size >= 256 else size,   # height
            0, 0,                         # palette colours, reserved
            1, 32,                        # planes, bits per pixel
            len(data), offset,
        ))
        payloads.append(data)
        offset += len(data)

    return struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(payloads)


def build_ico(path: str = ICO_PATH) -> str:
    frames = {size: _draw(size) for size in ICO_SIZES}
    with open(path, "wb") as fh:
        fh.write(_ico_bytes(frames))
    return path


def build_png(path: str = PNG_PATH) -> str:
    _draw(256).save(path, format="PNG", optimize=True)
    return path


def build_preview(path: str = PREVIEW_PATH) -> str:
    """A labelled contact sheet, useful for reviewing the artwork."""
    from PIL import Image, ImageDraw

    sizes = (16, 24, 32, 48, 64, 128)
    zoom = 3
    gutter, label_h = 18, 18
    cell_w = max(sizes) * zoom + gutter
    width = cell_w * len(sizes)
    height = max(sizes) * zoom + gutter + label_h

    sheet = Image.new("RGBA", (width, height), (250, 250, 251, 255))
    d = ImageDraw.Draw(sheet)

    # Checkerboard so transparency is visible.
    for cy in range(0, height, 12):
        for cx in range(0, width, 12):
            if (cx // 12 + cy // 12) % 2 == 0:
                d.rectangle([cx, cy, cx + 11, cy + 11], fill=(238, 238, 240, 255))

    for i, size in enumerate(sizes):
        frame = _draw(size).resize((size * zoom, size * zoom), Image.NEAREST)
        x = i * cell_w + gutter // 2
        y = gutter // 2 + (max(sizes) * zoom - frame.height) // 2
        sheet.alpha_composite(frame, (x, y))
        d.text((x, height - label_h + 2), f"{size}px", fill=(70, 70, 76, 255))

    sheet.convert("RGB").save(path, format="PNG", optimize=True)
    return path


def _stale(paths) -> list:
    if not all(os.path.exists(p) for p in paths):
        return [p for p in paths if not os.path.exists(p)]
    icon_mtime = os.path.getmtime(ICO_PATH)
    return [ICO_PATH] if os.path.getmtime(PNG_PATH) < icon_mtime else []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the committed icon files are missing")
    args = ap.parse_args(argv)

    paths = (ICO_PATH, PNG_PATH, PREVIEW_PATH)

    if args.check:
        missing = _stale(paths)
        if missing:
            print("Missing icon files: " + ", ".join(missing), file=sys.stderr)
            print("Run: python assets/make_icon.py", file=sys.stderr)
            return 1
        print("Icon files present.")
        return 0

    if not os.path.isdir(HERE):
        os.makedirs(HERE, exist_ok=True)
    build_ico()
    build_png()
    build_preview()
    print("Wrote:")
    for p in paths:
        print(f"  {p}  ({os.path.getsize(p):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
