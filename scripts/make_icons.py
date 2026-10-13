"""Draws the home-screen icons in docs/icons (run once; needs Pillow): python scripts/make_icons.py

A dark glass tile with three past candles and an orange forecast candle, matching the page colours.
Icons are full-bleed squares; iOS and Android round the corners themselves.
"""
from PIL import Image, ImageDraw, ImageFilter

S = 1024
BG, UP, DOWN, PRED = (7, 10, 18), (52, 209, 191), (255, 107, 107), (245, 166, 35)


def tile(pad=0.0):
    img = Image.new("RGB", (S, S), BG)
    glow = Image.new("RGB", (S, S), BG)
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -350, 700, 650), fill=(29, 78, 216))          # blue glow, top left
    g.ellipse((450, 450, 1350, 1350), fill=(15, 118, 110))         # teal glow, bottom right
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(170)), 0.55)
    d = ImageDraw.Draw(img)
    k = 1 - 2 * pad                                                 # shrink the drawing for maskable icons
    def box(x0, y0, x1, y1):
        return tuple(S * pad + v * k for v in (x0, y0, x1, y1))
    # (centre x, wick top, wick bottom, body top, body bottom, colour)
    candles = [(250, 560, 800, 610, 740, DOWN), (420, 430, 700, 470, 640, UP),
               (590, 330, 590, 360, 520, UP), (770, 210, 470, 240, 380, PRED)]
    for cx, wt, wb, bt, bb, col in candles:
        d.rounded_rectangle(box(cx - 9, wt, cx + 9, wb), radius=9 * k, fill=col)
        d.rounded_rectangle(box(cx - 52, bt, cx + 52, bb), radius=16 * k, fill=col)
    return img


if __name__ == "__main__":
    full, safe = tile(), tile(pad=0.12)
    for name, img, size in (("apple-touch-icon.png", full, 180), ("icon-192.png", full, 192),
                            ("icon-512.png", full, 512), ("maskable-512.png", safe, 512)):
        img.resize((size, size), Image.LANCZOS).save(f"docs/icons/{name}", optimize=True)
    full.resize((32, 32), Image.LANCZOS).save("docs/icons/favicon-32.png", optimize=True)
