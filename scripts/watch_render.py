#!/usr/bin/env python3
"""An original, generic rectangular smartwatch body drawn with Pillow around the 240x240 display, the one side button lit
when pressed (right edge). No product artwork or logo.
watch(frame, pressed, r): `frame` is the PNG from out/frames, `pressed` a key of BUTTONS or None, r the output scale."""
from PIL import Image, ImageDraw, ImageFilter

W, H = 420, 600  # design units; the display is 1.2x its pixels (288 x 288) at r = 1
ACCENT = (255, 150, 40)
# name: (side, y centre, label); the key is the overlay.board `buttons` line number (0 = P0.13)
BUTTONS = {0: ("R", 300, "Button")}
CASE = (45, 140, 375, 460)
_cache = {}


def _body(pressed, r):
    k = 2 * r  # draw at 2x the output and downsample
    S = lambda *v: tuple(x * k for x in v)
    im = Image.new("RGB", (round(W * k), round(H * k)), (236, 238, 241))
    d = ImageDraw.Draw(im)
    for box in ((130, 0, 290, 150), (130, 450, 290, 600)):  # straps
        d.rectangle(S(*box), fill=(52, 55, 61))
    for y in (520, 546):
        d.ellipse(S(205, y - 5, 215, y + 5), fill=(20, 21, 24))
    for n, (side, cy, _) in BUTTONS.items():
        on = n == pressed
        x0, x1 = (31, 49) if side == "L" else (371, 389)
        if on:  # pressed: sits 5 units deeper, lit with a soft glow
            x0, x1 = (x0 + 5, x1 + 5) if side == "L" else (x0 - 5, x1 - 5)
            glow = Image.new("L", im.size, 0)
            ImageDraw.Draw(glow).rounded_rectangle(S(x0 - 8, cy - 38, x1 + 8, cy + 38), round(12 * k), fill=255)
            im.paste(Image.new("RGB", im.size, ACCENT), mask=glow.filter(ImageFilter.GaussianBlur(9 * k)).point(lambda v: min(255, v * 3)))
            d = ImageDraw.Draw(im)
        d.rounded_rectangle(S(x0, cy - 36, x1, cy + 36), round(6 * k), fill=ACCENT if on else (84, 88, 96))
    d.rounded_rectangle(S(*CASE), round(40 * k), fill=(34, 36, 41), outline=(14, 15, 17), width=round(2 * k))
    d.rounded_rectangle(S(CASE[0] + 9, CASE[1] + 9, CASE[2] - 9, CASE[3] - 9), round(34 * k), fill=(14, 15, 17))
    return im.resize((round(W * r), round(H * r)), Image.LANCZOS)


def watch(frame, pressed=None, r=1):
    if (pressed, r) not in _cache:
        _cache[pressed, r] = _body(pressed, r)
    im = _cache[pressed, r].copy()
    sz = (round(288 * r), round(288 * r))
    im.paste(frame.convert("RGB").resize(sz, Image.NEAREST), (round(66 * r), round(156 * r)))
    return im


if __name__ == "__main__":
    for n in (None, 0):
        watch(Image.new("RGB", (240, 240), (200, 205, 190)), n).save(f"/tmp/watch_{n}.png")
