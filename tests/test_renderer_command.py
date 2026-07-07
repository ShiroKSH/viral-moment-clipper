from pathlib import Path

from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.services.edit_planner import build_edit_plan
from backend.services.renderer import build_ffmpeg_command


def test_renderer_command_contains_vertical_filters_badge_overlay_and_fallback_codec(tmp_path):
    settings = Settings()
    clip = ClipCandidate(
        id="clip_001",
        moment_id="moment_001",
        start=1,
        end=31,
        duration=30,
        final_score=88,
        moment_type="insight",
        hook_text="hook",
        summary="summary",
        reason="reason",
        text="some transcript",
        suggested_title="title",
        suggested_caption="caption",
    )
    plan = build_edit_plan(clip, settings)
    badge = tmp_path / "badge.png"
    badge.write_bytes(b"png")

    command = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings, ass_path=Path("clip.ass"), badge_path=badge)
    joined = " ".join(command)

    assert "-filter_complex" in command
    assert "scale=1080:1920" in joined
    assert "min(iw\\,1080)" in joined
    assert "overlay" in joined
    assert "subtitles=filename" in joined
    assert "drawbox" in joined
    assert "-loop" in command
    assert "[1:v]format=rgba" in joined
    assert f"main_h-overlay_h-{settings.branding.badge_safe_bottom_px}" in joined
    assert joined.index("[badged]subtitles") > joined.index("[1:v]format=rgba")
    assert "setsar=1[vout]" in joined
    assert "h264_nvenc" in command

    fallback = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings, codec="libx264")
    assert "libx264" in fallback
    assert "-crf" in fallback
    assert "18" in fallback
