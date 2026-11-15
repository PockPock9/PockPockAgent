"""Draws the PockPock Agent app icon (public/icon.png and public/icon.ico). Run: python scripts/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 512
out = Path(__file__).resolve().parent.parent / "public"
image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
gradient = Image.new("RGBA", (SIZE, SIZE))
for y in range(SIZE):
    for x in range(0, SIZE, 4):
        t = (x + y) / (2 * SIZE)
        color = (int(139 + (90 - 139) * t), int(108 + (170 - 108) * t), int(255 + (245 - 255) * t), 255)
        for dx in range(4):
            gradient.putpixel((x + dx, y), color)
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle((16, 16, SIZE - 16, SIZE - 16), radius=112, fill=255)
image.paste(gradient, (0, 0), mask)
draw = ImageDraw.Draw(image)
font = None
for name in ("segoeuib.ttf", "arialbd.ttf"):
    try:
        font = ImageFont.truetype(name, 300)
        break
    except OSError:
        continue
font = font or ImageFont.load_default()
box = draw.textbbox((0, 0), "P", font=font)
draw.text(((SIZE - (box[2] - box[0])) / 2 - box[0], (SIZE - (box[3] - box[1])) / 2 - box[1] - 6), "P", font=font, fill=(255, 255, 255, 255))
image.save(out / "icon.png")
image.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote", out / "icon.png", out / "icon.ico")
