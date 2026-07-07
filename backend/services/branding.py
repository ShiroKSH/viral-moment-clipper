from __future__ import annotations

from pathlib import Path

from backend.core.config import Settings


def generate_badge(path: Path, config: Settings) -> Path | None:
    if not config.branding.show_badge:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    width = config.branding.badge_width
    height = 92
    image = Image.new("RGBA", (width, height), (0, 0, 0, int(255 * config.branding.opacity)))
    draw = ImageDraw.Draw(image)
    radius = 18
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(0, 0, 0, int(255 * config.branding.opacity)))
    icon_x = 30
    icon_y = 24
    icon_w = 58
    icon_h = 42
    draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_w, icon_y + icon_h), radius=11, fill=(255, 0, 0, 255))
    triangle = [
        (icon_x + 24, icon_y + 12),
        (icon_x + 24, icon_y + icon_h - 12),
        (icon_x + icon_w - 17, icon_y + icon_h / 2),
    ]
    draw.polygon(triangle, fill=(255, 255, 255, 255))
    text = config.branding.badge_text
    max_text_width = width - (icon_x + icon_w + 48)
    font = ImageFont.load_default()
    for size in range(38, 23, -2):
        try:
            candidate = ImageFont.truetype("arial.ttf", size)
        except OSError:
            candidate = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if bbox[2] - bbox[0] <= max_text_width or size == 24:
            font = candidate
            break
    bbox = draw.textbbox((0, 0), text, font=font)
    while bbox[2] - bbox[0] > max_text_width and len(text) > 4:
        text = text[:-4].rstrip() + "..."
        bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((icon_x + icon_w + 24, (height - (bbox[3] - bbox[1])) / 2 - 4), text, fill=(255, 255, 255, 255), font=font)
    image.save(path)
    return path
