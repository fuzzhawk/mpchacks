#!/usr/bin/env python3
"""
mksplash.py - generate the MPC1000.BMP boot splash.

JJOS looks for a file called MPC1000.BMP in the root of the CompactFlash card
at start-up.  If it is there, it is drawn full screen for about three seconds
INSTEAD of the normal text splash; if it is missing, the text splash is drawn.
No firmware patching is involved.

The format is fixed by the parser at flash 0x0162BC in JJOS 3.16:

  * a standard Windows BMP; only bfOffBits (byte 10), biWidth (18),
    biHeight (22) and biSizeImage (34) are read, each as 16-bit little-endian
  * 1 bit per pixel, most significant bit leftmost
  * row stride = biSizeImage / biHeight, with a floor of 32 bytes
  * rows are consumed bottom-up, which is normal BMP order
  * width is clamped to 240 and height to 64 - the LCD is 240x64
  * a set bit writes 0 to the framebuffer and a clear bit writes 15, so a
    normal black-on-white BMP comes out as dark artwork on the display.
    Pass --invert if your display shows it the other way round.

The artwork is a mourning cloak (Nymphalis antiopa): dark wings, the pale
ragged margin the species is named for, and the row of spots just inside it.

Usage:
    mksplash.py -o MPC1000.BMP [--invert] [--preview] [--text "morningcloak os"]
"""

import argparse
import struct

W, H = 240, 64
STRIDE = 32                      # (240 + 31) // 32 * 4
INK, BG = 0, 1                   # 1bpp values: 0 = lit on the LCD


# Wing outlines, in units of the body half-height, for the right-hand side.
# The left side is the mirror image.
FOREWING = [(0.04, -0.20), (0.12, -0.58), (0.28, -0.84), (0.52, -0.98),
            (0.80, -0.92), (0.96, -0.74), (1.00, -0.50), (0.92, -0.30),
            (0.72, -0.18), (0.44, -0.13), (0.16, -0.13)]
HINDWING = [(0.06, -0.05), (0.32, -0.05), (0.58, 0.08), (0.72, 0.32),
            (0.70, 0.60), (0.54, 0.82), (0.32, 0.92), (0.12, 0.84),
            (0.04, 0.58), (0.03, 0.22)]


def _centroid(pts):
    return (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))


def _inset(pts, c, f):
    cx, cy = c
    return [(cx + (x - cx) * f, cy + (y - cy) * f) for x, y in pts]


def butterfly(g, cx, cy, s, ss, f_band=0.86, f_inner=0.70):
    """
    A mourning cloak, drawn at supersampled scale.

    Detail is deliberately sparse.  At 56 px tall on a 1-bit display the
    species' blue spot row turns to speckle and destroys the silhouette, so
    what is kept is the one cue that still reads at this size: broad dark
    wings inside the pale ragged margin the butterfly is named for.

    The margin is three nested fills - dark rim, pale band, dark interior -
    rather than a stroked outline.  Stroking an inset path puts half the pen
    width outside the shape, which at this scale breaks up into a dashed halo
    floating around the wings instead of a border on them.
    """
    for base in (FOREWING, HINDWING):
        for side in (1, -1):
            pts = [(cx + side * x * s, cy + y * s) for x, y in base]
            c = _centroid(pts)
            g.polygon(pts, fill=0)
            g.polygon(_inset(pts, c, f_band), fill=255)
            g.polygon(_inset(pts, c, f_inner), fill=0)
    g.ellipse([cx - 1.4 * ss, cy - 0.66 * s, cx + 1.4 * ss, cy + 0.68 * s], fill=0)
    g.ellipse([cx - 2.2 * ss, cy - 0.76 * s, cx + 2.2 * ss, cy - 0.56 * s], fill=0)
    for sg in (-1, 1):
        g.line([(cx, cy - 0.70 * s), (cx + sg * 6 * ss, cy - 0.94 * s),
                (cx + sg * 10 * ss, cy - 1.06 * s)], fill=0, width=int(1.4 * ss))
        ex, ey = cx + sg * 10 * ss, cy - 1.06 * s
        r = 1.5 * ss
        g.ellipse([ex - r, ey - r, ex + r, ey + r], fill=0)


def draw(text='morningcloak os'):
    from PIL import Image, ImageDraw, ImageFont

    SS = 8
    big = Image.new('L', (W * SS, H * SS), 255)
    butterfly(ImageDraw.Draw(big), 44 * SS, 32 * SS, 28 * SS, SS)
    # BOX is an area average, which thresholds to clean solid edges;
    # LANCZOS rings and leaves the wings speckled.
    img = big.resize((W, H), Image.BOX).point(lambda v: 0 if v < 140 else 255)

    # text at final resolution so it stays crisp on the LCD
    d = ImageDraw.Draw(img)
    name, _, suffix = text.rpartition(' ')
    if not name:
        name, suffix = text, ''
    x = 86
    for size in (22, 20, 18, 16, 14):
        f = ImageFont.load_default(size=size)
        if d.textbbox((0, 0), name, font=f)[2] <= W - x - 4:
            break
    d.text((x, 12), name, fill=0, font=f)
    if suffix:
        d.text((x + 2, 40), suffix, fill=0, font=ImageFont.load_default(size=16))
    return img


def to_bmp(img, invert=False):
    """Pack a PIL image into the 1-bpp BMP the JJOS parser expects."""
    px = img.convert('L').load()
    rows = []
    for y in range(H - 1, -1, -1):              # bottom-up
        row = bytearray(STRIDE)
        for x in range(W):
            dark = px[x, y] < 128
            bit = INK if dark else BG
            if invert:
                bit ^= 1
            if bit:
                row[x >> 3] |= 0x80 >> (x & 7)
        rows.append(bytes(row))
    pixels = b''.join(rows)

    pal = struct.pack('<4B4B', 0, 0, 0, 0, 255, 255, 255, 0)   # idx0 black, idx1 white
    offbits = 14 + 40 + len(pal)
    info = struct.pack('<IiiHHIIiiII', 40, W, H, 1, 1, 0, len(pixels),
                       0, 0, 2, 2)
    hdr = struct.pack('<2sIHHI', b'BM', offbits + len(pixels), 0, 0, offbits)
    return hdr + info + pal + pixels


def preview(img):
    px = img.convert('L').load()
    print('+' + '-' * W + '+')
    for y in range(H):
        print('|' + ''.join('#' if px[x, y] < 128 else ' ' for x in range(W)) + '|')
    print('+' + '-' * W + '+')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-o', '--out', default='MPC1000.BMP')
    ap.add_argument('--text', default='morningcloak os')
    ap.add_argument('--invert', action='store_true')
    ap.add_argument('--preview', action='store_true')
    ap.add_argument('--png', help='also write a PNG for viewing on a computer')
    a = ap.parse_args()

    img = draw(a.text)
    if a.preview:
        preview(img)
    data = to_bmp(img, a.invert)
    with open(a.out, 'wb') as f:
        f.write(data)
    print(f'wrote {a.out}: {len(data)} bytes, {W}x{H}, 1bpp'
          + (' (inverted)' if a.invert else ''))
    if a.png:
        img.save(a.png)
        print(f'wrote {a.png}')


if __name__ == '__main__':
    main()
