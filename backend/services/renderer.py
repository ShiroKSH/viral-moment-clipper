from __future__ import annotations

from pathlib import Path
import textwrap

from backend.core.config import Settings
from backend.core.ffmpeg import run_command
from backend.schemas.clips import ClipCandidate
from backend.schemas.render import EditPlan


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _drawtext_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", " ").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def _hook_title_lines(value: str, max_chars: int = 26, max_lines: int = 2) -> list[str]:
    lines = textwrap.wrap(" ".join(value.split()), width=max_chars, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= max_lines:
        return lines
    clipped = lines[:max_lines]
    clipped[-1] = clipped[-1][: max_chars - 3].rstrip() + "..."
    return clipped


def _zoom_width_expr(base_width: int, edit_plan: EditPlan) -> str:
    expr = f"min(iw\\,{base_width})"
    zooms = [operation for operation in edit_plan.operations if operation.type == "punch_zoom" and operation.start is not None and operation.end is not None][:4]
    for operation in reversed(zooms):
        duration = max(0.1, operation.end - operation.start)
        lift = max(0.01, float(operation.scale_to or 1.08) - 1)
        pulse = f"min(iw\\,{base_width}*(1+{lift:.3f}*sin((t-{operation.start:.2f})/{duration:.2f}*3.14159)))"
        expr = f"if(between(t\\,{operation.start:.2f}\\,{operation.end:.2f})\\,{pulse}\\,{expr})"
    return expr


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


def _operation_windows(edit_plan: EditPlan, operation_type: str) -> list[tuple[float, float]]:
    return [
        (operation.start, operation.end)
        for operation in edit_plan.operations
        if operation.type == operation_type and operation.start is not None and operation.end is not None and operation.end > operation.start
    ]


def build_ffmpeg_command(
    source_path: Path,
    output_path: Path,
    clip: ClipCandidate,
    edit_plan: EditPlan,
    config: Settings,
    ass_path: Path | None = None,
    badge_path: Path | None = None,
    codec: str | None = None,
) -> list[str]:
    width = config.render.width
    height = config.render.height
    duration = max(clip.duration, 1)
    filter_parts: list[str] = ["[0:v]split=2[bgsrc][fgsrc]"]
    if config.render.mode == "center_crop":
        filter_parts.append(f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},setsar=1[base]")
    else:
        zoom_expr = _zoom_width_expr(width, edit_plan)
        filter_parts.append(
            f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height},boxblur=28:2,eq=brightness=-0.10:saturation=0.85[bg]"
        )
        filter_parts.append(
            f"[fgsrc]scale=w='{zoom_expr}':h=-2:eval=frame:flags=lanczos,setsar=1,"
            "eq=contrast=1.04:saturation=1.06,unsharp=5:5:0.65:3:3:0.30[fg]"
        )
        filter_parts.append("[bg][fg]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame[base]")
    current = "base"
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
        filter_parts.append(f"[{current}]drawbox=x=0:y=0:w='iw*t/{duration:.2f}':h=12:color=white@0.85:t=fill[progressed]")
        current = "progressed"
    for index, (start, end) in enumerate(_operation_windows(edit_plan, "micro_flash")):
        next_label = f"flash{index}"
        filter_parts.append(f"[{current}]drawbox=x=0:y=0:w=iw:h=ih:color=white@0.055:t=fill:enable='between(t\\,{start:.2f}\\,{end:.2f})'[{next_label}]")
        current = next_label
    for index, (start, end) in enumerate(_operation_windows(edit_plan, "focus_frame")):
        next_label = f"focus{index}"
        filter_parts.append(
            f"[{current}]drawbox=x=46:y=430:w=iw-92:h=ih-850:color=white@0.16:t=5:"
            f"enable='between(t\\,{start:.2f}\\,{end:.2f})'[{next_label}]"
        )
        current = next_label
    use_badge_overlay = config.branding.show_badge and badge_path and badge_path.exists()
    if use_badge_overlay:
        filter_parts.append(f"[1:v]format=rgba,scale={config.branding.badge_width}:-1[badge]")
        filter_parts.append(
            f"[{current}][badge]overlay=x='(main_w-overlay_w)/2':"
            f"y='main_h-overlay_h-{config.branding.badge_safe_bottom_px}'[badged]"
        )
        current = "badged"
    elif config.branding.show_badge:
        text = _drawtext_text(config.branding.badge_text)
        y = f"ih-{config.branding.badge_safe_bottom_px}-86"
        filter_parts.append(f"[{current}]drawbox=x=(iw-620)/2:y={y}:w=620:h=86:color=black@0.55:t=fill[badgebg]")
        filter_parts.append(f"[badgebg]drawtext=text='{text}':x=(w-text_w)/2:y={y}+24:fontcolor=white:fontsize=36:borderw=2:bordercolor=black@0.6[badged]")
        current = "badged"
    if ass_path:
        filter_parts.append(f"[{current}]subtitles=filename='{_filter_path(ass_path)}':original_size={width}x{height}[subbed]")
        current = "subbed"
    filter_parts.append(f"[{current}]setsar=1[vout]")
    argv = [
        config.paths.ffmpeg_path,
        "-y",
        "-ss",
        f"{clip.start:.3f}",
        "-i",
        str(source_path),
    ]
    if use_badge_overlay:
        argv.extend(["-loop", "1", "-i", str(badge_path)])
    argv.extend([
        "-t",
        f"{duration:.3f}",
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
        "-map",
        "0:a?",
        "-r",
        str(config.render.fps),
        "-c:v",
        codec or config.render.video_codec,
        "-b:v",
        config.render.video_bitrate,
        "-c:a",
        config.render.audio_codec,
        "-b:a",
        config.render.audio_bitrate,
        "-shortest",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    if codec == "libx264":
        argv[argv.index("-b:v") : argv.index("-c:a")] = ["-preset", "medium", "-crf", "18"]
    return argv


def render_clip(source_path: Path, output_path: Path, clip: ClipCandidate, edit_plan: EditPlan, config: Settings, ass_path: Path | None = None, badge_path: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    primary = build_ffmpeg_command(source_path, output_path, clip, edit_plan, config, ass_path=ass_path, badge_path=badge_path)
    try:
        run_command(primary, timeout=None)
    except Exception:
        fallback = build_ffmpeg_command(source_path, output_path, clip, edit_plan, config, ass_path=ass_path, badge_path=badge_path, codec=config.render.fallback_video_codec)
        run_command(fallback, timeout=None)
    return output_path
