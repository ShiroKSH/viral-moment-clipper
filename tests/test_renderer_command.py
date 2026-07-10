from pathlib import Path

import pytest

from backend.core.errors import AppError
from backend.core.config import Settings
from backend.schemas.clips import ClipCandidate
from backend.schemas.render import EditOperation
from backend.services.edit_planner import build_edit_plan
from backend.services import renderer
from backend.services.renderer import (
    RenderIntegrityError,
    build_ffmpeg_command,
    render_acceleration_summary,
    render_clip,
    verify_render_integrity,
)


def test_renderer_command_uses_cuda_filters_for_nvenc_blurred_background(tmp_path):
    settings = Settings()
    settings.render.gpu_filters = True
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
    plan.operations.extend(
        [
            EditOperation(type="evidence_stamp", start=2.4, end=3.7, text="500 ЛЕТ"),
            EditOperation(type="audio_accent", start=2.4, end=2.58, text="evidence"),
            EditOperation(type="shot_motion", start=4, end=10, scale_from=1.0, scale_to=1.022),
        ]
    )
    badge = tmp_path / "badge.png"
    badge.write_bytes(b"png")

    command = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings, ass_path=Path("clip.ass"), badge_path=badge)
    joined = " ".join(command)

    assert "-filter_complex" in command
    assert "-hwaccel_output_format" in command
    assert "scale_cuda=360:640:interp_algo=bilinear" in joined
    assert "scale_cuda=1080:1920" in joined
    assert "scale_cuda=1080:-2" in joined
    assert "force_original_aspect_ratio=increase" in joined
    assert "crop=360:640" in joined
    assert "bilateral_cuda=sigmaS=10:sigmaR=512:window_size=31" in joined
    assert "[bgcanvas]" not in joined
    assert "[bgfill_src]" not in joined
    assert "overlay_cuda" in joined
    assert "hwdownload" in joined
    assert "subtitles=filename" in joined
    assert "[mainvsrc]subtitles=" in joined
    assert "[subbed]split=" not in joined
    assert "drawbox" in joined
    assert "-loop" not in command
    assert "[1:v]format=rgba" not in joined
    assert "setsar=1[mainv]" in joined
    assert "concat=n=2:v=1:a=0[vout]" in joined
    assert "concat=n=2:v=0:a=1[aout]" in joined
    assert "loudnorm=I=-16:LRA=7:TP=-2.2" in joined
    assert "aevalsrc=" in joined
    assert "[aout]" in command
    assert "0:a?" not in command
    assert "Продолжение" in joined
    assert "ПОЛНОЕ ВИДЕО" not in joined
    assert "на YouTube" in joined
    assert "полная мысль" not in joined
    assert "drawtext=text='YT':x=133" in joined
    assert "drawtext=text='500 ЛЕТ'" in joined
    assert "adelay=2400:all=1" in joined
    assert "[ctaframe]trim=start=" in joined
    assert "select='eq(n\\,0)'" in joined
    cta_frames = int(round(max(0.8, settings.end_card.duration_sec) * settings.render.fps))
    assert f"loop=loop={cta_frames - 1}:size=1:start=0" in joined
    assert f"loop=loop={cta_frames - 1}:size=1:start=0,copy" in joined
    assert "setpts=N/(30*TB)" in joined
    assert "gblur=sigma=3" in joined
    assert "eq=brightness=-0.03:saturation=0.94" in joined
    assert "color=0x080a0d@0.16" in joined
    assert ",fade=t=out:st=" not in joined
    assert "[ctaframe]trim=start=29.967:end=30.033" in joined
    assert "zoompan=" not in joined
    assert "fps=30,scale=1104:1964" in joined
    assert "scale=1100:1956" in joined
    assert "color=c=0x0b0d10" not in joined
    assert "-shortest" not in command
    assert "h264_nvenc" in command
    assert "-hwaccel" in command
    assert "cuda" in command
    assert "-preset" in command
    assert settings.render.nvenc_preset in command
    assert "-cq" in command
    assert str(settings.render.nvenc_cq) in command
    assert command[command.index("-filter_complex_threads") + 1] == "1"
    assert "subtitles=CPU/libass" in render_acceleration_summary(settings, Path("clip.ass"))
    assert f"end_card={settings.end_card.duration_sec:.1f}s" in render_acceleration_summary(settings, Path("clip.ass"))
    assert "end_sound=motion-hit" in render_acceleration_summary(settings, Path("clip.ass"))
    assert "audio=loudnorm" in render_acceleration_summary(settings, Path("clip.ass"))
    assert "background/blur/overlay=CUDA" in render_acceleration_summary(settings, Path("clip.ass"))
    assert "montage_motion=CPU post-filter" in render_acceleration_summary(settings, Path("clip.ass"))
    assert "trunc(1080*" in joined
    assert "scale_cuda=360:640:interp_algo=bilinear:format=yuv420p" in joined
    assert "bilateral_cuda=sigmaS=10:sigmaR=512:window_size=31,scale_cuda=1080:1920:interp_algo=bilinear:format=yuv420p" in joined
    assert "scale_cuda=1080:-2:interp_algo=lanczos:format=yuv420p" in joined

    fallback = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings, codec="libx264")
    assert "libx264" in fallback
    assert "-crf" in fallback
    assert "18" in fallback
    assert "-hwaccel" not in fallback


def test_renderer_can_disable_cuda_filters_for_cpu_effect_graph(tmp_path):
    settings = Settings()
    settings.render.gpu_filters = False
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

    command = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings)
    joined = " ".join(command)

    assert "scale=1080:1920" in joined
    assert "boxblur=42:3" in joined
    assert "min(iw\\,1080)" in joined
    assert "scale=w='" in joined
    assert "[composed]scale=w='trunc(1080*" not in joined
    assert "overlay_cuda" not in joined
    assert "-hwaccel_output_format" not in command
    assert "blur/overlay=CPU filters" in render_acceleration_summary(settings)


def test_inline_badge_is_only_used_when_end_card_is_disabled(tmp_path):
    settings = Settings()
    settings.end_card.enabled = False
    clip = ClipCandidate(
        id="clip_badge",
        moment_id="moment_badge",
        start=0,
        end=5,
        duration=5,
        final_score=80,
        moment_type="insight",
        hook_text="hook",
        summary="summary",
        reason="reason",
        text="text",
        suggested_title="title",
        suggested_caption="caption",
    )
    plan = build_edit_plan(clip, settings)
    badge = tmp_path / "badge.png"
    badge.write_bytes(b"png")

    command = build_ffmpeg_command(Path("in.mp4"), Path("out.mp4"), clip, plan, settings, badge_path=badge)
    joined = " ".join(command)

    assert "-loop" in command
    assert "[1:v]format=rgba" in joined
    assert f"main_h-overlay_h-{settings.branding.badge_safe_bottom_px}" in joined
    assert "enable='between(t\\,0.65\\,2.20)'" in joined


def test_renderer_requires_gpu_when_configured(monkeypatch, tmp_path):
    settings = Settings()
    settings.render.require_gpu = True
    clip = ClipCandidate(
        id="clip_001",
        moment_id="moment_001",
        start=1,
        end=4,
        duration=3,
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
    monkeypatch.setattr(renderer, "_probe_encoder", lambda ffmpeg_path, codec: "driver too old")

    with pytest.raises(AppError, match="h264_nvenc unavailable"):
        render_clip(Path("in.mp4"), tmp_path / "out.mp4", clip, plan, settings)


def test_render_integrity_rejects_audio_longer_than_truncated_video(monkeypatch, tmp_path):
    settings = Settings()
    clip = ClipCandidate(
        id="clip_integrity",
        moment_id="moment_integrity",
        start=0,
        end=20,
        duration=20,
        final_score=80,
        moment_type="insight",
        hook_text="hook",
        summary="summary",
        reason="reason",
        text="text",
        suggested_title="title",
        suggested_caption="caption",
    )
    monkeypatch.setattr(
        renderer,
        "ffprobe_json",
        lambda *_: {
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "16.0",
                    "nb_frames": "480",
                    "width": 1080,
                    "height": 1920,
                },
                {"codec_type": "audio", "duration": "21.4"},
            ]
        },
    )

    with pytest.raises(RenderIntegrityError, match="video stream is 16.00s"):
        verify_render_integrity(tmp_path / "broken.mp4", clip, settings)
