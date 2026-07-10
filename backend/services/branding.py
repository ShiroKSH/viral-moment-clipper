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
    height = max(62, int(width * 0.15))
    image = Image.new("RGBA", (width, height), (0, 0, 0, int(255 * config.branding.opacity)))
    draw = ImageDraw.Draw(image)
    radius = max(12, int(height * 0.22))
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=(0, 0, 0, int(255 * config.branding.opacity)))
    icon_x = max(22, int(width * 0.045))
    icon_h = int(height * 0.48)
    icon_w = int(icon_h * 1.38)
    icon_y = (height - icon_h) // 2
    draw.rounded_rectangle((icon_x, icon_y, icon_x + icon_w, icon_y + icon_h), radius=max(8, int(icon_h * 0.24)), fill=(255, 0, 0, 255))
    triangle = [
        (icon_x + int(icon_w * 0.42), icon_y + int(icon_h * 0.28)),
        (icon_x + int(icon_w * 0.42), icon_y + int(icon_h * 0.72)),
        (icon_x + int(icon_w * 0.72), icon_y + icon_h / 2),
    ]
    draw.polygon(triangle, fill=(255, 255, 255, 255))
    text = config.branding.badge_text
    text_x = icon_x + icon_w + max(18, int(width * 0.04))
    max_text_width = width - text_x - max(20, int(width * 0.04))
    font = ImageFont.load_default()
    for size in range(max(24, int(height * 0.42)), 19, -2):
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
    draw.text((text_x, (height - (bbox[3] - bbox[1])) / 2 - 4), text, fill=(255, 255, 255, 255), font=font)
    image.save(path)
    return path
