"""Draws the PockPock Agent app icon (public/icon.png and public/icon.ico). Run: python scripts/make_icon.py

The mark is a chicken foot whose centre toe is a lightning bolt. Geometry is on a 256-unit grid and
matches public/favicon.svg.
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

INK = (20, 17, 28, 255)
FEATHER = (255, 244, 214, 255)
VOLT = (255, 214, 10, 255)

MARK = 0.66  # mark width as a share of the tile
GAP = 12  # ink gap around the bolt, in 256-grid units

BOLT = [(138, 28), (92, 130), (122, 130), (108, 230), (172, 108), (140, 108), (168, 28)]
# Side toes: a bent stroke (knuckle) ending in a pointed claw
TOE_LEFT = [(116, 73), (51, 119), (26, 216), (73, 137), (132, 95)]
TOE_RIGHT = [(140, 73), (205, 119), (230, 216), (183, 137), (124, 95)]


def to_canvas(points, size, offset):
    k = size / 256
    return [(offset[0] + x * k, offset[1] + y * k) for x, y in points]


def layer(points, canvas):
    mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def render(size):
    scale = 4 if size <= 256 else 2  # supersample, then downsample for clean edges
    CANVAS = size * scale
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))

    tile = Image.new("L", (CANVAS, CANVAS), 0)
    inset = int(size * 16 / 512 * scale)
    ImageDraw.Draw(tile).rounded_rectangle(
        (inset, inset, CANVAS - inset, CANVAS - inset), radius=int(0.22 * (CANVAS - 2 * inset)), fill=255
    )
    image.paste(Image.new("RGBA", (CANVAS, CANVAS), INK), (0, 0), tile)

    tile_size = CANVAS - 2 * inset
    mark_size = tile_size * MARK
    offset = (CANVAS / 2 - mark_size / 2, CANVAS / 2 - mark_size / 2)

    for toe in (TOE_LEFT, TOE_RIGHT):
        image.paste(Image.new("RGBA", (CANVAS, CANVAS), FEATHER), (0, 0), layer(to_canvas(toe, mark_size, offset), CANVAS))

    bolt_mask = layer(to_canvas(BOLT, mark_size, offset), CANVAS)
    # Dilate the bolt by drawing its outline as a wide stroke (much faster than a rank filter)
    gap_px = max(2, round(GAP * mark_size / 256))
    gap_mask = bolt_mask.copy()
    bolt_points = to_canvas(BOLT, mark_size, offset)
    ImageDraw.Draw(gap_mask).line(bolt_points + [bolt_points[0]], fill=255, width=gap_px, joint="curve")
    image.paste(Image.new("RGBA", (CANVAS, CANVAS), INK), (0, 0), ImageChops.multiply(gap_mask, tile))
    image.paste(Image.new("RGBA", (CANVAS, CANVAS), VOLT), (0, 0), bolt_mask)

    return image.resize((size, size), Image.LANCZOS)


def main():
    root = Path(__file__).resolve().parent.parent
    out = root / "public"
    brand = root.parent / "design-system" / "brand" / "png"
    brand.mkdir(parents=True, exist_ok=True)
    master = render(1024)
    master.resize((512, 512), Image.LANCZOS).save(out / "icon.png")
    master.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    master.save(out / "icon.icns")
    for size in (1024, 512, 256, 128, 64, 32, 16):
        render(size).save(brand / f"pockpock-icon-{size}.png")
    print("wrote", out / "icon.png", out / "icon.ico", out / "icon.icns", brand)


if __name__ == "__main__":
    main()
