"""Draws Dugout's icon (the web app's logo: a football on a grass-green tile) as a Windows .ico."""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
# the rim patches of the logo (viewBox 32, the same as the SVG in web/index.html)
PATCHES = [[(20.88, 9.29), (18.29, 4.22), (26.5, 10.18)], [(23.89, 18.56), (27.91, 14.54), (24.78, 24.18)],
           [(16, 24.3), (21.07, 26.88), (10.93, 26.88)], [(8.11, 18.56), (7.22, 24.18), (4.09, 14.54)],
           [(11.12, 9.29), (5.5, 10.18), (13.71, 4.22)]]


def tile(size=256, rounded=True):
    s = size
    grad = Image.new('RGBA', (s, s))
    top, bottom = (34, 197, 94), (6, 95, 70)
    px = grad.load()
    for y in range(s):
        for x in range(s):
            t = (x + y) / (2 * s - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,)
    mask = Image.new('L', (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22) if rounded else 0, fill=255)
    img = Image.new('RGBA', (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    # the same drawing as the SVG logo (viewBox 32): a white ball r 11.2, a black pentagon, five seams; drawn 4x
    # larger and scaled down (smooth edges)
    big = Image.new('RGBA', (s * 4, s * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    ink = (4, 19, 10, 255)
    u = s * 4 / 32
    off = 0.0 if rounded else 0.0
    c, r = 16 * u, 11.2 * u
    d.ellipse((c - r, c - r, c + r, c + r), fill=(255, 255, 255, 255), outline=ink, width=max(1, int(1.4 * u)))
    pent = [(16, 11.8), (20, 14.7), (18.5, 19.4), (13.5, 19.4), (12, 14.7)]
    d.polygon([(x * u, y * u) for x, y in pent], fill=ink)
    for (x0, y0), (x1, y1) in zip(pent, [(16, 4.9), (26.6, 12.6), (22.6, 25), (9.4, 25), (5.4, 12.6)]):
        d.line((x0 * u, y0 * u, x1 * u, y1 * u), fill=ink, width=max(1, int(1.3 * u)))
    # the black patches at the rim, between the seams (clipped to the ball)
    patches = Image.new('RGBA', big.size, (0, 0, 0, 0))
    pd = ImageDraw.Draw(patches)
    for tri in PATCHES:
        pd.polygon([(x * u, y * u) for x, y in tri], fill=ink)
    clip = Image.new('L', big.size, 0)
    ImageDraw.Draw(clip).ellipse((c - r, c - r, c + r, c + r), fill=255)
    big.paste(patches, (0, 0), Image.composite(patches.split()[3], Image.new('L', big.size, 0), clip))
    d.ellipse((c - r, c - r, c + r, c + r), outline=ink, width=max(1, int(1.4 * u)))
    img.alpha_composite(big.resize((s, s), Image.LANCZOS))
    return img


def main():
    img = tile(256)
    out = os.path.join(HERE, 'Dugout.ico')
    img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(os.path.join(HERE, '..', 'web', 'icon.png'))
    tile(512, rounded=False).save(os.path.join(HERE, '..', 'web', 'icon-512.png'))   # phone home screen (square)
    print(out)


if __name__ == '__main__':
    main()
