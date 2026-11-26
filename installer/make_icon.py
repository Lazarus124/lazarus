"""Genera installer/lazarus.ico (ícono simple, sin dependencias de diseño)."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).with_name("lazarus.ico")
img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(31, 78, 121, 255))
try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 170)
except OSError:
    font = ImageFont.load_default(size=170)
d.text((128, 132), "L", font=font, fill=(255, 255, 255, 255), anchor="mm")
d.ellipse((168, 52, 204, 88), fill=(255, 196, 0, 255))
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print(out)
