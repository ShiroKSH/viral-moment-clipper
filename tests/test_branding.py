from pathlib import Path

from PIL import Image

from backend.core.config import Settings
from backend.services.branding import generate_badge


def test_generate_badge_handles_long_text_inside_configured_width(tmp_path: Path):
    settings = Settings()
    settings.branding.badge_width = 420
    settings.branding.badge_text = "@very_long_youtube_handle_that_must_not_overflow_the_badge"
    path = generate_badge(tmp_path / "badge.png", settings)

    assert path is not None
    with Image.open(path) as image:
        assert image.size == (420, 63)
