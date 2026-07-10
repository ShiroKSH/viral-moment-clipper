from __future__ import annotations

from functools import lru_cache
import hashlib
import math
from pathlib import Path
import shutil
import textwrap

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.core.ffmpeg import ffprobe_json, run_command
from backend.core.paths import resolve_project_path
from backend.schemas.clips import ClipCandidate
from backend.schemas.render import EditOperation, EditPlan


class RenderIntegrityError(AppError):
    pass


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _safe_subtitle_path(ass_path: Path | None, config: Settings) -> Path | None:
    if not ass_path or not ass_path.exists():
        return ass_path
    source = ass_path.resolve()
    digest = hashlib.sha1(str(source).encode("utf-8")).hexdigest()
    destination = resolve_project_path(config.paths.temp_dir) / "ffmpeg_ass" / f"{digest}.ass"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.stat().st_mtime_ns < source.stat().st_mtime_ns:
        shutil.copyfile(source, destination)
    return destination


def _drawtext_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", " ").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _hook_title_lines(value: str, max_chars: int = 26, max_lines: int = 2) -> list[str]:
    lines = textwrap.wrap(" ".join(value.split()), width=max_chars, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= max_lines:
        return lines
    clipped = lines[:max_lines]
    clipped[-1] = clipped[-1][: max_chars - 3].rstrip() + "..."
    return clipped


def _timed_operations(edit_plan: EditPlan, operation_type: str, limit: int | None = None) -> list[EditOperation]:
    operations = [
        operation
        for operation in edit_plan.operations
        if operation.type == operation_type
        and operation.start is not None
        and operation.end is not None
        and operation.end > operation.start
    ]
    return operations if limit is None else operations[:limit]


def _has_operation(edit_plan: EditPlan, operation_type: str) -> bool:
    return any(operation.type == operation_type for operation in edit_plan.operations)


def _zoom_width_expr(base_width: int, edit_plan: EditPlan) -> str:
    expr = f"min(iw\\,{base_width})"
    zooms = _timed_operations(edit_plan, "punch_zoom", limit=4)
    for operation in reversed(zooms):
        duration = max(0.1, operation.end - operation.start)
        lift = max(0.01, float(operation.scale_to or 1.08) - 1)
        pulse = f"min(iw\\,{base_width}*(1+{lift:.3f}*sin((t-{operation.start:.2f})/{duration:.2f}*3.14159)))"
        expr = f"if(between(t\\,{operation.start:.2f}\\,{operation.end:.2f})\\,{pulse}\\,{expr})"
    return expr


def _crop_height_expr(base_height: int, edit_plan: EditPlan) -> str:
    expr = f"{base_height}*1.035"
    zooms = _timed_operations(edit_plan, "punch_zoom", limit=5)
    for operation in reversed(zooms):
        zoom_duration = max(0.1, operation.end - operation.start)
        lift = max(0.01, float(operation.scale_to or 1.07) - 1)
        pulse = f"{base_height}*(1.035+{lift * 0.75:.3f}*sin((t-{operation.start:.2f})/{zoom_duration:.2f}*3.14159))"
        expr = f"if(between(t\\,{operation.start:.2f}\\,{operation.end:.2f})\\,{pulse}\\,{expr})"
    return expr


def _composite_motion_scale_expr(edit_plan: EditPlan) -> str:
    expr = "1.0"
    zooms = _timed_operations(edit_plan, "punch_zoom", limit=4)
    for operation in reversed(zooms):
        zoom_duration = max(0.1, operation.end - operation.start)
        lift = max(0.008, min(0.08, float(operation.scale_to or 1.04) - 1))
        pulse = f"1+{lift:.3f}*sin((t-{operation.start:.2f})/{zoom_duration:.2f}*3.14159)"
        expr = f"if(between(t\\,{operation.start:.2f}\\,{operation.end:.2f})\\,{pulse}\\,{expr})"
    return expr


def _append_composite_motion(
    filters: list[str],
    label: str,
    next_label: str,
    edit_plan: EditPlan,
    width: int,
    height: int,
) -> None:
    scale = _composite_motion_scale_expr(edit_plan)
    filters.append(
        f"[{label}]scale=w='trunc({width}*({scale})/2)*2':"
        f"h='trunc({height}*({scale})/2)*2':eval=frame:flags=bicubic,"
        f"crop={width}:{height}:x='(iw-ow)/2':y='(ih-oh)/2',setsar=1[{next_label}]"
    )


def _shot_motion_offset_expr(edit_plan: EditPlan, amplitude: float, *, invert: bool = False) -> str:
    expression = "0.0"
    motions = _timed_operations(edit_plan, "shot_motion", limit=3)
    for operation in reversed(motions):
        start = float(operation.start or 0)
        end = float(operation.end or start + 1)
        duration = max(0.2, end - start)
        direction = 1 if float(operation.scale_to or 1.0) >= float(operation.scale_from or 1.0) else -1
        if invert:
            direction *= -1
        progress = f"min(max((t-{start:.2f})/{duration:.2f}\\,0)\\,1)"
        eased = f"0.5-0.5*cos(PI*({progress}))"
        offset = f"{direction * amplitude:.2f}*({eased})"
        expression = f"if(between(t\\,{start:.2f}\\,{end:.2f})\\,{offset}\\,{expression})"
    return expression


def _append_shot_motion(
    filters: list[str],
    label: str,
    next_label: str,
    edit_plan: EditPlan,
    width: int,
    height: int,
    fps: int,
) -> None:
    motions = _timed_operations(edit_plan, "shot_motion", limit=3)
    max_scale = max(
        [1.012]
        + [float(operation.scale_from or 1.0) for operation in motions]
        + [float(operation.scale_to or 1.0) for operation in motions]
    )
    overscan = max(1.012, min(1.028, max_scale))
    scaled_width = int(math.ceil(width * overscan / 2) * 2)
    scaled_height = int(math.ceil(height * overscan / 2) * 2)
    x_amplitude = min(8.0, max(2.0, (scaled_width - width) * 0.22))
    y_amplitude = min(10.0, max(2.0, (scaled_height - height) * 0.18))
    x_offset = _shot_motion_offset_expr(edit_plan, x_amplitude)
    y_offset = _shot_motion_offset_expr(edit_plan, y_amplitude, invert=True)
    filters.append(
        f"[{label}]fps={fps},scale={scaled_width}:{scaled_height}:flags=bicubic,"
        f"crop={width}:{height}:x='(iw-ow)/2+({x_offset})':y='(ih-oh)/2+({y_offset})',"
        f"setsar=1[{next_label}]"
    )


def _append_drawtext(filters: list[str], label: str, next_label: str, *, text: str, x: str, y: str, fontsize: int, enable: str | None = None, box: bool = False) -> None:
    parts = [
        f"[{label}]drawtext=text='{_drawtext_text(text)}'",
        f"x={x}",
        f"y={y}",
        "fontcolor=white",
        f"fontsize={fontsize}",
        "borderw=4",
        "bordercolor=black@0.85",
    ]
    if box:
        parts.extend(["box=1", "boxcolor=black@0.45", "boxborderw=24"])
    if enable:
        parts.append(f"enable='{enable}'")
    filters.append(":".join(parts) + f"[{next_label}]")


def _append_evidence_stamp(
    filters: list[str],
    label: str,
    next_label: str,
    operation: EditOperation,
    index: int,
) -> None:
    start = float(operation.start or 0)
    end = float(operation.end or start + 1.2)
    text = _drawtext_text((operation.text or "").upper())
    enter = f"min(max((t-{start:.2f})/0.18\\,0)\\,1)"
    alpha = (
        f"if(lt(t\\,{start + 0.14:.2f})\\,(t-{start:.2f})/0.14\\,"
        f"if(gt(t\\,{end - 0.18:.2f})\\,({end:.2f}-t)/0.18\\,1))"
    )
    enabled = f"between(t\\,{start:.2f}\\,{end:.2f})"
    bar_label = f"evidencebar{index}"
    filters.append(
        f"[{label}]drawbox=x=118:y=286:w=8:h='112*{enter}':"
        f"color=0xff3154@0.96:t=fill:enable='{enabled}'[{bar_label}]"
    )
    filters.append(
        f"[{bar_label}]drawtext=text='{text}':x=154:y='294+30*(1-{enter})':"
        "fontcolor=0xffd54a:fontsize=82:borderw=5:bordercolor=black@0.78:"
        f"alpha='{alpha}':enable='{enabled}'[{next_label}]"
    )


def _append_end_card(filters: list[str], label: str, next_label: str, config: Settings, width: int, height: int) -> None:
    duration = max(0.8, config.end_card.duration_sec)
    raw_headline = " ".join(config.end_card.headline.split())
    if " на " in raw_headline:
        before, after = raw_headline.split(" на ", 1)
        headline_lines = [before, f"на {after}"]
    else:
        headline_lines = _hook_title_lines(raw_headline, max_chars=16, max_lines=2) or [raw_headline]
    subheadline = " ".join(config.end_card.subheadline.split())
    channel = _drawtext_text(config.end_card.channel_text or config.branding.badge_text or config.branding.handle)
    text_enter = "(1-min(t/0.58\\,1))"
    scaled_width = int(math.ceil(width * 1.018 / 2) * 2)
    scaled_height = int(math.ceil(height * 1.018 / 2) * 2)
    pan = f"sin(PI*t/{duration:.3f})"
    filters.append(
        f"[{label}]scale={scaled_width}:{scaled_height}:flags=bicubic,"
        f"crop={width}:{height}:x='(iw-ow)/2+6*{pan}':y='(ih-oh)/2-5*{pan}',"
        "gblur=sigma=3:steps=2,eq=brightness=-0.03:saturation=0.94,"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=0x080a0d@0.16:t=fill,"
        "setsar=1[cta0]"
    )
    filters.append("[cta0]drawbox=x=116:y=638:w='190*min(t/0.42\\,1)':h=8:color=0xff3154@0.96:t=fill[cta1]")
    current = "cta1"
    base_y = 684 if len(headline_lines) > 1 else 744
    for index, line in enumerate(headline_lines):
        text = _drawtext_text(line)
        front = f"ctahead{index}"
        y = base_y + index * 92
        filters.append(
            f"[{current}]drawtext=text='{text}':x=116:y={y}+34*{text_enter}:"
            "fontcolor=white:fontsize=82:borderw=4:bordercolor=black@0.58"
            f"[{front}]"
        )
        current = front
    channel_y = base_y + len(headline_lines) * 92 + 72
    if subheadline:
        sub_y = base_y + len(headline_lines) * 92 + 28
        filters.append(
            f"[{current}]drawtext=text='{_drawtext_text(subheadline)}':x=116:y={sub_y}+22*{text_enter}:"
            "fontcolor=0xd8dde6:fontsize=38:borderw=2:bordercolor=black@0.42[ctasub]"
        )
        current = "ctasub"
        channel_y = sub_y + 82
    filters.append(f"[{current}]drawbox=x=116:y={channel_y}:w=86:h=58:color=0xff0033@0.96:t=fill[cta10]")
    filters.append(
        f"[cta10]drawtext=text='YT':x=133:y={channel_y + 13}:"
        "fontcolor=white:fontsize=31:borderw=1:bordercolor=black@0.25[cta11]"
    )
    filters.append(
        f"[cta11]drawtext=text='{channel}':x=226:y={channel_y + 8}:"
        "fontcolor=white:fontsize=43:borderw=3:bordercolor=black@0.52[cta12]"
    )
    filters.append(f"[cta12]format=yuv420p,setsar=1[{next_label}]")


def _end_card_audio_source(config: Settings) -> str:
    duration = max(0.8, config.end_card.duration_sec)
    left = "0.24*sin(2*PI*(520+780*t)*t)*exp(-7.2*t)+0.10*sin(2*PI*1180*t)*exp(-12*t)+0.035*sin(2*PI*210*t)*exp(-3.2*t)"
    right = "0.22*sin(2*PI*(560+720*t)*t)*exp(-7.2*t)+0.09*sin(2*PI*1260*t)*exp(-12*t)+0.032*sin(2*PI*224*t)*exp(-3.2*t)"
    return f"aevalsrc={left}|{right}:s=44100:d={duration:.3f}"


def _main_audio_chain(duration: float, edit_plan: EditPlan) -> str:
    parts = [f"atrim=0:{duration:.3f}", "asetpts=PTS-STARTPTS"]
    if _has_operation(edit_plan, "audio_normalization"):
        parts.append("loudnorm=I=-16:LRA=7:TP=-2.2")
    parts.append("aformat=sample_rates=44100:channel_layouts=stereo")
    return ",".join(parts)


def _append_main_audio(
    filters: list[str],
    duration: float,
    edit_plan: EditPlan,
    next_label: str,
    input_index: int,
) -> None:
    accents = _timed_operations(edit_plan, "audio_accent", limit=1)
    if not accents:
        filters.append(f"[{input_index}:a]{_main_audio_chain(duration, edit_plan)}[{next_label}]")
        return

    filters.append(f"[{input_index}:a]{_main_audio_chain(duration, edit_plan)}[speech]")
    accent_labels: list[str] = []
    for index, operation in enumerate(accents):
        delay_ms = max(0, int(round(float(operation.start or 0) * 1000)))
        accent_label = f"accenta{index}"
        left = "0.095*sin(2*PI*(560+1350*t)*t)*exp(-24*t)"
        right = "0.088*sin(2*PI*(610+1260*t)*t)*exp(-24*t)"
        filters.append(
            f"aevalsrc={left}|{right}:s=44100:d=0.18,"
            f"adelay={delay_ms}:all=1,aformat=sample_rates=44100:channel_layouts=stereo[{accent_label}]"
        )
        accent_labels.append(accent_label)
    inputs = "[speech]" + "".join(f"[{label}]" for label in accent_labels)
    filters.append(
        f"{inputs}amix=inputs={1 + len(accent_labels)}:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.86:level=0[{next_label}]"
    )


def _append_end_card_audio(
    filters: list[str],
    input_index: int,
    duration: float,
    config: Settings,
    edit_plan: EditPlan,
    speech_input_index: int,
) -> None:
    cta_duration = max(0.8, config.end_card.duration_sec)
    volume = max(0.0, min(1.0, config.end_card.sound_volume))
    fade_start = max(0.20, cta_duration - 0.38)
    _append_main_audio(filters, duration, edit_plan, "maina", speech_input_index)
    filters.append(
        f"[{input_index}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
        f"volume={volume:.2f},afade=t=out:st={fade_start:.2f}:d=0.34,"
        "alimiter=limit=0.88:level=0[ctaa]"
    )
    filters.append("[maina][ctaa]concat=n=2:v=0:a=1[aout]")


def _operation_windows(edit_plan: EditPlan, operation_type: str) -> list[tuple[float, float]]:
    return [(operation.start, operation.end) for operation in _timed_operations(edit_plan, operation_type)]


def _is_nvenc(codec: str) -> bool:
    return codec.endswith("_nvenc")


def render_acceleration_summary(config: Settings, ass_path: Path | None = None, codec: str | None = None) -> str:
    active_codec = codec or config.render.video_codec
    parts = [f"encode={active_codec}"]
    if _is_nvenc(active_codec):
        parts.append("nvenc=GPU")
        parts.append(f"hwaccel_decode={config.render.hwaccel or 'off'}")
        parts.append(f"gpu_filters={'on' if _uses_cuda_filters(config, active_codec) else 'off'}")
        parts.append(f"preset={config.render.nvenc_preset}")
        parts.append(f"cq={config.render.nvenc_cq}")
    else:
        parts.append("encode=CPU")
    if ass_path:
        parts.append("subtitles=CPU/libass")
    if config.dynamic_edit.audio_normalization_enabled:
        parts.append("audio=loudnorm")
    if config.end_card.enabled:
        parts.append(f"end_card={config.end_card.duration_sec:.1f}s")
        if config.end_card.sound_enabled:
            parts.append("end_sound=motion-hit")
    if config.render.mode == "blurred_background":
        if _uses_cuda_filters(config, active_codec):
            parts.append("background/blur/overlay=CUDA")
            parts.append("text/badge=CPU filters")
            if config.dynamic_edit.punch_zoom_enabled:
                parts.append("montage_motion=CPU post-filter")
        else:
            parts.append("blur/overlay=CPU filters")
    return ", ".join(parts)


def _uses_cuda_filters(config: Settings, codec: str) -> bool:
    return bool(
        config.render.gpu_filters
        and config.render.mode == "blurred_background"
        and _is_nvenc(codec)
        and (config.render.hwaccel or "").lower() == "cuda"
    )


@lru_cache(maxsize=16)
def _probe_encoder(ffmpeg_path: str, codec: str) -> str | None:
    if codec in {"libx264", "libx265"}:
        return None
    argv = [
        ffmpeg_path,
        "-hide_banner",
        "-f",
        "lavfi",
        "-i",
        "color=size=256x256:rate=30:duration=0.2",
        "-frames:v",
        "1",
        "-c:v",
        codec,
        "-f",
        "null",
        "-",
    ]
    try:
        run_command(argv, timeout=30)
    except AppError as exc:
        return str(exc)
    return None


def build_ffmpeg_command(
    source_path: Path,
    output_path: Path,
    clip: ClipCandidate,
    edit_plan: EditPlan,
    config: Settings,
    ass_path: Path | None = None,
    badge_path: Path | None = None,
    codec: str | None = None,
    audio_path: Path | None = None,
    source_has_audio: bool = True,
) -> list[str]:
    width = config.render.width
    height = config.render.height
    duration = max(clip.duration, 1)
    active_codec = codec or config.render.video_codec
    use_cuda_filters = _uses_cuda_filters(config, active_codec)
    foreground_width = width
    use_end_card = config.end_card.enabled and config.end_card.duration_sec > 0
    show_inline_badge = config.branding.show_badge and not use_end_card
    use_badge_overlay = bool(show_inline_badge and badge_path and badge_path.exists())
    badge_input_index = 1 + int(audio_path is not None)
    audio_input_index = 1 if audio_path else (0 if source_has_audio else None)
    use_end_card_sound = use_end_card and config.end_card.sound_enabled and audio_input_index is not None
    normalize_audio = _has_operation(edit_plan, "audio_normalization")
    semantic_audio = bool(_timed_operations(edit_plan, "audio_accent", limit=1))
    processed_audio = (normalize_audio or semantic_audio) and audio_input_index is not None
    filter_parts: list[str] = ["[0:v]setpts=PTS-STARTPTS,split=2[bgsrc][fgsrc]"]
    if use_cuda_filters:
        filter_parts.append(
            "[bgsrc]scale_cuda=360:640:interp_algo=bilinear:format=yuv420p:"
            "force_original_aspect_ratio=increase:force_divisible_by=2[bgfill]"
        )
        filter_parts.append(
            "[bgfill]crop=360:640:x='(iw-ow)/2':y='(ih-oh)/2'[bgcrop]"
        )
        filter_parts.append(
            f"[bgcrop]bilateral_cuda=sigmaS=10:sigmaR=512:window_size=31,"
            f"scale_cuda={width}:{height}:interp_algo=bilinear:format=yuv420p[bg]"
        )
        filter_parts.append(
            f"[fgsrc]scale_cuda={foreground_width}:-2:interp_algo=lanczos:format=yuv420p[fg]"
        )
        filter_parts.append("[bg][fg]overlay_cuda=x='(W-w)/2':y='(H-h)/2'[gpucomposed]")
        filter_parts.append("[gpucomposed]hwdownload,format=yuv420p,setsar=1[composed]")
        if _timed_operations(edit_plan, "punch_zoom", limit=4):
            _append_composite_motion(filter_parts, "composed", "motion", edit_plan, width, height)
            gpu_base = "motion"
        else:
            gpu_base = "composed"
        filter_parts.append(f"[{gpu_base}]drawbox=x=0:y=0:w=iw:h=ih:color=black@0.015:t=fill[base]")
    elif config.render.mode == "center_crop":
        crop_height_expr = _crop_height_expr(height, edit_plan)
        filter_parts.append(
            f"[fgsrc]scale=w=-2:h='{crop_height_expr}':eval=frame:flags=lanczos,"
            f"crop={width}:{height}:x='(iw-ow)/2':y='(ih-oh)/2',"
            "setsar=1,eq=contrast=1.03:saturation=1.04,unsharp=5:5:0.45:3:3:0.18[base]"
        )
    else:
        zoom_expr = _zoom_width_expr(foreground_width, edit_plan)
        filter_parts.append(
            f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},boxblur=42:3,eq=brightness=-0.12:saturation=0.80[bg]"
        )
        filter_parts.append(
            f"[fgsrc]scale=w='{zoom_expr}':h=-2:eval=frame:flags=lanczos,setsar=1,"
            "eq=contrast=1.03:saturation=1.04,unsharp=5:5:0.45:3:3:0.18[fg]"
        )
        filter_parts.append("[bg][fg]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame[base]")
    current = "base"
    if _timed_operations(edit_plan, "shot_motion", limit=3):
        _append_shot_motion(filter_parts, current, "shotmotion", edit_plan, width, height, config.render.fps)
        current = "shotmotion"
    if any(operation.type == "hook_title" for operation in edit_plan.operations):
        title = next((operation.text for operation in edit_plan.operations if operation.type == "hook_title" and operation.text), clip.hook_text)
        title_lines = _hook_title_lines(title or clip.hook_text)
        if title_lines:
            box_height = 82 + 54 * len(title_lines)
            filter_parts.append(f"[{current}]drawbox=x=64:y=68:w=iw-128:h={box_height}:color=black@0.42:t=fill:enable='between(t\\,0\\,2.60)'[hookbox]")
            current = "hookbox"
            for line_index, line in enumerate(title_lines):
                next_label = "hooked" if line_index == len(title_lines) - 1 else f"hookline{line_index}"
                _append_drawtext(
                    filter_parts,
                    current,
                    next_label,
                    text=line,
                    x="(w-text_w)/2",
                    y=str(96 + line_index * 56),
                    fontsize=46,
                    enable="between(t\\,0\\,2.60)",
                )
                current = next_label
    if any(operation.type == "progress_bar" for operation in edit_plan.operations):
        filter_parts.append(f"[{current}]drawbox=x=0:y=0:w='iw*t/{duration:.2f}':h=8:color=white@0.60:t=fill[progressed]")
        current = "progressed"
    for index, (start, end) in enumerate(_operation_windows(edit_plan, "micro_flash")):
        next_label = f"flash{index}"
        filter_parts.append(f"[{current}]drawbox=x=0:y=0:w=iw:h=ih:color=white@0.055:t=fill:enable='between(t\\,{start:.2f}\\,{end:.2f})'[{next_label}]")
        current = next_label
    for index, operation in enumerate(_timed_operations(edit_plan, "evidence_stamp", limit=2)):
        next_label = f"evidence{index}"
        _append_evidence_stamp(filter_parts, current, next_label, operation, index)
        current = next_label
    brand_enable = f"between(t\\,0.65\\,{min(duration, 2.20):.2f})"
    if use_badge_overlay:
        filter_parts.append(f"[{badge_input_index}:v]format=rgba,scale={config.branding.badge_width}:-1[badge]")
        filter_parts.append(
            f"[{current}][badge]overlay=x='(main_w-overlay_w)/2':"
            f"y='main_h-overlay_h-{config.branding.badge_safe_bottom_px}':"
            f"shortest=1:enable='{brand_enable}'[badged]"
        )
        current = "badged"
    elif show_inline_badge:
        text = _drawtext_text(config.branding.badge_text)
        badge_height = max(62, int(config.branding.badge_width * 0.15))
        font_size = max(24, int(badge_height * 0.40))
        box_y = f"ih-{config.branding.badge_safe_bottom_px}-{badge_height}"
        text_y = f"h-{config.branding.badge_safe_bottom_px}-{int(badge_height * 0.68)}"
        filter_parts.append(
            f"[{current}]drawbox=x=(iw-{config.branding.badge_width})/2:y={box_y}:"
            f"w={config.branding.badge_width}:h={badge_height}:color=black@{config.branding.opacity:.2f}:"
            f"t=fill:enable='{brand_enable}'[badgebg]"
        )
        filter_parts.append(
            f"[badgebg]drawtext=text='{text}':x=(w-text_w)/2:y={text_y}:fontcolor=white:"
            f"fontsize={font_size}:borderw=2:bordercolor=black@0.45:enable='{brand_enable}'[badged]"
        )
        current = "badged"
    if use_end_card:
        cta_duration = max(0.8, config.end_card.duration_sec)
        cta_frames = max(1, int(round(cta_duration * config.render.fps)))
        frame_step = 1 / max(1, config.render.fps)
        freeze_start = max(0.0, duration - frame_step)
        freeze_end = duration + frame_step
        filter_parts.append(f"[{current}]split=2[mainvsrc][ctaframe]")
        if ass_path:
            filter_parts.append(
                f"[mainvsrc]subtitles=filename='{_filter_path(ass_path)}':original_size={width}x{height},setsar=1[mainv]"
            )
        else:
            filter_parts.append("[mainvsrc]setsar=1[mainv]")
        filter_parts.append(
            f"[ctaframe]trim=start={freeze_start:.3f}:end={freeze_end:.3f},"
            "select='eq(n\\,0)',setpts=PTS-STARTPTS,"
            f"loop=loop={cta_frames - 1}:size=1:start=0,copy,"
            f"setpts=N/({config.render.fps}*TB)[ctasrc]"
        )
        _append_end_card(filter_parts, "ctasrc", "ctav", config, width, height)
        filter_parts.append("[mainv][ctav]concat=n=2:v=1:a=0[vout]")
        if use_end_card_sound:
            cta_audio_input_index = 1 + int(audio_path is not None) + int(use_badge_overlay)
            _append_end_card_audio(
                filter_parts,
                cta_audio_input_index,
                duration,
                config,
                edit_plan,
                audio_input_index,
            )
    else:
        if ass_path:
            filter_parts.append(f"[{current}]subtitles=filename='{_filter_path(ass_path)}':original_size={width}x{height}[subbed]")
            current = "subbed"
        filter_parts.append(f"[{current}]setsar=1[vout]")
    if processed_audio and not use_end_card_sound:
        _append_main_audio(filter_parts, duration, edit_plan, "aout", audio_input_index)
    argv = [
        config.paths.ffmpeg_path,
        "-y",
    ]
    if _is_nvenc(active_codec) and config.render.hwaccel:
        argv.extend(["-hwaccel", config.render.hwaccel])
    if use_cuda_filters:
        argv.extend(["-hwaccel_output_format", "cuda"])
    argv.extend(["-ss", f"{clip.start:.3f}", "-t", f"{duration:.3f}", "-i", str(source_path)])
    if audio_path:
        argv.extend(["-ss", f"{clip.start:.3f}", "-t", f"{duration:.3f}", "-i", str(audio_path)])
    if use_badge_overlay:
        argv.extend(["-loop", "1", "-i", str(badge_path)])
    if use_end_card_sound:
        argv.extend([
            "-f",
            "lavfi",
            "-t",
            f"{config.end_card.duration_sec:.3f}",
            "-i",
            _end_card_audio_source(config),
        ])
    audio_map = "[aout]" if use_end_card_sound or processed_audio else f"{audio_input_index}:a?" if audio_input_index is not None else None
    argv.extend([
        "-filter_complex_threads",
        "1",
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
    ])
    if audio_map:
        argv.extend(["-map", audio_map])
    argv.extend([
        "-r",
        str(config.render.fps),
        "-c:v",
        active_codec,
    ])
    if _is_nvenc(active_codec):
        argv.extend([
            "-preset",
            config.render.nvenc_preset,
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            str(config.render.nvenc_cq),
            "-b:v",
            config.render.video_bitrate,
            "-spatial_aq",
            "1",
            "-aq-strength",
            "8",
        ])
    elif active_codec == "libx264":
        argv.extend(["-preset", "medium", "-crf", "18"])
    else:
        argv.extend(["-b:v", config.render.video_bitrate])
    argv.extend([
        "-c:a",
        config.render.audio_codec,
        "-b:a",
        config.render.audio_bitrate,
    ])
    if not use_end_card:
        argv.append("-shortest")
    argv.extend([
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    return argv


def verify_render_integrity(
    output_path: Path,
    clip: ClipCandidate,
    config: Settings,
    *,
    expect_audio: bool = True,
) -> dict:
    raw = ffprobe_json(config.paths.ffprobe_path, output_path)
    streams = raw.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    expected_duration = clip.duration + (
        max(0.8, config.end_card.duration_sec) if config.end_card.enabled and config.end_card.duration_sec > 0 else 0
    )
    video_duration = float((video or {}).get("duration") or 0)
    audio_duration = float((audio or {}).get("duration") or 0)
    frame_count = int((video or {}).get("nb_frames") or 0)
    encoder = str(((video or {}).get("tags") or {}).get("encoder") or "")
    tolerance = max(0.22, 4 / max(1, config.render.fps))
    errors: list[str] = []
    if video is None:
        errors.append("missing video stream")
    else:
        if int(video.get("width") or 0) != config.render.width or int(video.get("height") or 0) != config.render.height:
            errors.append(
                f"unexpected canvas {video.get('width')}x{video.get('height')}"
            )
        if video_duration < expected_duration - tolerance:
            errors.append(f"video stream is {video_duration:.2f}s, expected {expected_duration:.2f}s")
        expected_frames = int((expected_duration - tolerance) * config.render.fps)
        if frame_count and frame_count < expected_frames:
            errors.append(f"video has {frame_count} frames, expected at least {expected_frames}")
    if expect_audio:
        if audio is None:
            errors.append("missing audio stream")
        elif audio_duration and audio_duration < expected_duration - tolerance:
            errors.append(f"audio stream is {audio_duration:.2f}s, expected {expected_duration:.2f}s")
        elif audio_duration > expected_duration + max(0.65, tolerance * 2):
            errors.append(f"audio stream is {audio_duration:.2f}s, expected {expected_duration:.2f}s")
    report = {
        "ok": not errors,
        "expected_duration": round(expected_duration, 3),
        "video_duration": round(video_duration, 3),
        "audio_duration": round(audio_duration, 3),
        "frame_count": frame_count,
        "width": int((video or {}).get("width") or 0),
        "height": int((video or {}).get("height") or 0),
        "encoder": encoder,
        "errors": errors,
    }
    if errors:
        raise RenderIntegrityError("Render integrity failed: " + "; ".join(errors))
    return report


def _source_has_audio(source_path: Path, config: Settings) -> bool:
    try:
        streams = ffprobe_json(config.paths.ffprobe_path, source_path).get("streams", [])
    except (AppError, TypeError, ValueError):
        return False
    return any(stream.get("codec_type") == "audio" for stream in streams)


def render_clip(
    source_path: Path,
    output_path: Path,
    clip: ClipCandidate,
    edit_plan: EditPlan,
    config: Settings,
    ass_path: Path | None = None,
    badge_path: Path | None = None,
    audio_path: Path | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    safe_ass_path = _safe_subtitle_path(ass_path, config)
    usable_audio_path = audio_path if audio_path and audio_path.exists() else None
    source_has_audio = bool(usable_audio_path) or _source_has_audio(source_path, config)
    primary_codec = config.render.video_codec
    primary_error = _probe_encoder(config.paths.ffmpeg_path, primary_codec)
    if primary_error is not None and config.render.require_gpu:
        raise AppError(f"{primary_codec} unavailable: {primary_error}")
    if primary_error is None:
        primary = build_ffmpeg_command(
            source_path,
            output_path,
            clip,
            edit_plan,
            config,
            ass_path=safe_ass_path,
            badge_path=badge_path,
            audio_path=usable_audio_path,
            source_has_audio=source_has_audio,
        )
        try:
            run_command(primary, timeout=None)
            verify_render_integrity(output_path, clip, config, expect_audio=source_has_audio)
            return output_path
        except RenderIntegrityError:
            raise
        except Exception as exc:
            primary_error = str(exc)
            if config.render.require_gpu:
                raise AppError(f"{primary_codec} failed: {primary_error}") from exc

    fallback = build_ffmpeg_command(
        source_path,
        output_path,
        clip,
        edit_plan,
        config,
        ass_path=safe_ass_path,
        badge_path=badge_path,
        codec=config.render.fallback_video_codec,
        audio_path=usable_audio_path,
        source_has_audio=source_has_audio,
    )
    try:
        run_command(fallback, timeout=None)
        verify_render_integrity(output_path, clip, config, expect_audio=source_has_audio)
    except Exception as exc:
        raise AppError(f"{primary_codec} failed: {primary_error}\n{config.render.fallback_video_codec} failed: {exc}") from exc
    return output_path
