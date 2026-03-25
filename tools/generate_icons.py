#!/usr/bin/env python
"""Generate .ico files for TireStorageManager and TSM-Installer.

Run once:
    python tools/generate_icons.py

Produces:
    assets/app.ico       – main app icon  (tire wheel)
    assets/installer.ico – installer icon  (wrench + gear)
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(exist_ok=True)

# ── colours ──────────────────────────────────────────────
BG       = (30, 41, 59)       # slate-800
TIRE     = (51, 65, 85)       # slate-700
RIM      = (148, 163, 184)    # slate-400
HUB      = (226, 232, 240)    # slate-200
ACCENT   = (59, 130, 246)     # blue-500
ORANGE   = (251, 146, 60)     # orange-400
DARK     = (15, 23, 42)       # slate-900
WHITE    = (241, 245, 249)


def _circle(draw, cx, cy, r, **kw):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)


def draw_tire(img_size=256):
    """A tyre seen from the front: outer rubber, rim ring, hub cap, lug nuts."""
    img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = img_size // 2
    s = img_size / 256  # scale factor

    # Outer rubber (tire)
    _circle(d, cx, cy, int(120 * s), fill=TIRE, outline=DARK, width=max(1, int(3 * s)))

    # Tread marks (subtle radial lines on the tire)
    for angle_deg in range(0, 360, 15):
        a = math.radians(angle_deg)
        x1 = cx + math.cos(a) * 95 * s
        y1 = cy + math.sin(a) * 95 * s
        x2 = cx + math.cos(a) * 118 * s
        y2 = cy + math.sin(a) * 118 * s
        d.line([(x1, y1), (x2, y2)], fill=DARK, width=max(1, int(2 * s)))

    # Rim
    _circle(d, cx, cy, int(82 * s), fill=RIM, outline=DARK, width=max(1, int(2 * s)))

    # Spoke pattern (5 spokes)
    for i in range(5):
        a = math.radians(i * 72 - 90)
        x2 = cx + math.cos(a) * 70 * s
        y2 = cy + math.sin(a) * 70 * s
        d.line([(cx, cy), (x2, y2)], fill=DARK, width=max(1, int(8 * s)))

    # Hub cap
    _circle(d, cx, cy, int(28 * s), fill=HUB, outline=DARK, width=max(1, int(2 * s)))

    # Centre accent circle
    _circle(d, cx, cy, int(14 * s), fill=ACCENT, outline=DARK, width=max(1, int(2 * s)))

    # Lug nuts
    for i in range(5):
        a = math.radians(i * 72 - 90)
        nx = cx + math.cos(a) * 20 * s
        ny = cy + math.sin(a) * 20 * s
        _circle(d, nx, ny, int(4 * s), fill=DARK)

    return img


def draw_installer(img_size=256):
    """A wrench + gear combo representing setup/installation."""
    img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = img_size // 2
    s = img_size / 256

    # Background circle
    _circle(d, cx, cy, int(120 * s), fill=BG, outline=ACCENT, width=max(1, int(4 * s)))

    # Gear (offset upper-right)
    gx = cx + int(25 * s)
    gy = cy - int(25 * s)
    gear_r = int(55 * s)
    tooth_r = int(68 * s)
    tooth_w = 18  # degrees

    # Gear teeth
    for i in range(8):
        a1 = math.radians(i * 45 - tooth_w / 2)
        a2 = math.radians(i * 45 + tooth_w / 2)
        points = [
            (gx + math.cos(a1) * gear_r * s / s, gy + math.sin(a1) * gear_r * s / s),
            (gx + math.cos(a1) * tooth_r * s / s, gy + math.sin(a1) * tooth_r * s / s),
            (gx + math.cos(a2) * tooth_r * s / s, gy + math.sin(a2) * tooth_r * s / s),
            (gx + math.cos(a2) * gear_r * s / s, gy + math.sin(a2) * gear_r * s / s),
        ]
        d.polygon(points, fill=RIM)

    # Gear body
    _circle(d, gx, gy, int(50 * s), fill=RIM, outline=DARK, width=max(1, int(2 * s)))
    # Gear hole
    _circle(d, gx, gy, int(20 * s), fill=BG, outline=DARK, width=max(1, int(2 * s)))

    # Wrench (diagonal from lower-left to centre)
    wrench_width = int(18 * s)
    # Shaft
    x1, y1 = cx - int(70 * s), cy + int(70 * s)
    x2, y2 = cx + int(10 * s), cy - int(10 * s)
    d.line([(x1, y1), (x2, y2)], fill=ORANGE, width=wrench_width)

    # Wrench head (open end) – a wider rectangle at the end
    head_len = int(30 * s)
    a = math.atan2(y1 - y2, x1 - x2)
    hx = x1 + math.cos(a) * 5 * s
    hy = y1 + math.sin(a) * 5 * s
    perp = a + math.pi / 2
    hw = int(14 * s)
    points = [
        (hx + math.cos(perp) * hw + math.cos(a) * head_len,
         hy + math.sin(perp) * hw + math.sin(a) * head_len),
        (hx - math.cos(perp) * hw + math.cos(a) * head_len,
         hy - math.sin(perp) * hw + math.sin(a) * head_len),
        (hx - math.cos(perp) * hw,
         hy - math.sin(perp) * hw),
        (hx + math.cos(perp) * hw,
         hy + math.sin(perp) * hw),
    ]
    d.polygon(points, fill=ORANGE, outline=DARK, width=max(1, int(2 * s)))

    # Small accent circle in gear centre
    _circle(d, gx, gy, int(8 * s), fill=ACCENT)

    return img


def save_ico(img, path):
    """Save as .ico with multiple sizes for crisp display at all scales."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [img.resize((sz, sz), Image.LANCZOS) for sz in sizes]
    frames[0].save(str(path), format="ICO", sizes=[(sz, sz) for sz in sizes],
                   append_images=frames[1:])


if __name__ == "__main__":
    app_img = draw_tire(256)
    inst_img = draw_installer(256)

    save_ico(app_img, ASSETS / "app.ico")
    save_ico(inst_img, ASSETS / "installer.ico")

    # Also save PNGs for preview
    app_img.save(str(ASSETS / "app.png"))
    inst_img.save(str(ASSETS / "installer.png"))

    print(f"✅ Created {ASSETS / 'app.ico'}")
    print(f"✅ Created {ASSETS / 'installer.ico'}")
    print(f"   (+ PNG previews)")
