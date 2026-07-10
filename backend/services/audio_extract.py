from __future__ import annotations

import subprocess
import wave
from pathlib import Path

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.core.ffmpeg import ffprobe_json, run_command
from backend.core.utils import write_json


SAMPLE_RATE = 16000
MIN_AUDIO_SECONDS = 0.5


def _positive_float(value: object) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _source_durations(source_path: Path, config: Settings) -> dict[str, float]:
    try:
        raw = ffprobe_json(config.paths.ffprobe_path, source_path)
    except (AppError, TypeError, ValueError):
        return {"video": 0.0, "audio": 0.0, "format": 0.0}

    streams = raw.get("streams", [])
    video = next(
        (
            stream
            for stream in streams
            if stream.get("codec_type") == "video" and not stream.get("disposition", {}).get("attached_pic")
        ),
        {},
    )
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    return {
        "video": _positive_float(video.get("duration")),
        "audio": _positive_float(audio.get("duration")),
        "format": _positive_float(raw.get("format", {}).get("duration")),
    }


def _target_duration(durations: dict[str, float]) -> tuple[float, str]:
    if durations["video"]:
        return durations["video"], "video"
    if durations["audio"]:
        return durations["audio"], "audio"
    if durations["format"]:
        return durations["format"], "format"
    return 0.0, "unknown"


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getframerate() != SAMPLE_RATE or audio.getsampwidth() != 2:
                return 0.0
            return audio.getnframes() / audio.getframerate()
    except (FileNotFoundError, OSError, EOFError, wave.Error):
        return 0.0


def audio_extraction_report_path(output_path: Path) -> Path:
    return output_path.with_suffix(".extract.json")


def _duration_is_usable(actual: float, expected: float) -> bool:
    if actual < MIN_AUDIO_SECONDS:
        return False
    if expected <= 0:
        return True
    tolerance = max(2.0, min(20.0, expected * 0.02))
    return actual >= expected - tolerance


def _decode_argv(
    source_path: Path,
    output_path: Path,
    config: Settings,
    *,
    target_duration: float,
    duration_source: str,
    recovery: bool,
) -> list[str]:
    argv = [config.paths.ffmpeg_path, "-hide_banner", "-loglevel", "error"]
    if recovery:
        argv.extend(["-fflags", "+discardcorrupt", "-err_detect", "ignore_err", "-max_error_rate", "1.0"])
    argv.extend(["-y", "-i", str(source_path), "-map", "0:a:0"])
    if target_duration:
        argv.extend(["-t", f"{target_duration:.3f}"])

    audio_filter = "aresample=async=1000:first_pts=0"
    if target_duration and duration_source == "video":
        audio_filter += f",apad=whole_dur={target_duration:.3f}"
    argv.extend(
        [
            "-vn",
            "-sn",
            "-dn",
            "-af",
            audio_filter,
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-acodec",
            "pcm_s16le",
            str(output_path),
        ]
    )
    return argv


def _finalize(
    temporary_path: Path,
    output_path: Path,
    *,
    source_path: Path,
    durations: dict[str, float],
    target_duration: float,
    duration_source: str,
    mode: str,
    decoder_messages: int,
) -> Path:
    actual_duration = wav_duration(temporary_path)
    temporary_path.replace(output_path)
    write_json(
        audio_extraction_report_path(output_path),
        {
            "source_path": str(source_path),
            "mode": mode,
            "duration_source": duration_source,
            "target_duration": round(target_duration, 3),
            "output_duration": round(actual_duration, 3),
            "source_durations": {key: round(value, 3) for key, value in durations.items()},
            "decoder_messages": decoder_messages,
        },
    )
    return output_path


def extract_wav(source_path: Path, output_path: Path, config: Settings) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.stem}.partial{output_path.suffix}")
    temporary_path.unlink(missing_ok=True)
    durations = _source_durations(source_path, config)
    target_duration, duration_source = _target_duration(durations)
    errors: list[AppError] = []

    for recovery in (False, True):
        temporary_path.unlink(missing_ok=True)
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = run_command(
                _decode_argv(
                    source_path,
                    temporary_path,
                    config,
                    target_duration=target_duration,
                    duration_source=duration_source,
                    recovery=recovery,
                ),
                timeout=None,
            )
        except AppError as exc:
            errors.append(exc)

        actual_duration = wav_duration(temporary_path)
        if _duration_is_usable(actual_duration, target_duration):
            decoder_messages = len((completed.stderr or "").splitlines()) if completed else 0
            if recovery:
                mode = "recovery"
            elif completed is None:
                mode = "salvaged_after_ffmpeg_error"
            elif decoder_messages:
                mode = "recovered_decoder_errors"
            else:
                mode = "normal"
            return _finalize(
                temporary_path,
                output_path,
                source_path=source_path,
                durations=durations,
                target_duration=target_duration,
                duration_source=duration_source,
                mode=mode,
                decoder_messages=decoder_messages,
            )

    temporary_path.unlink(missing_ok=True)
    detail = str(errors[-1]) if errors else "FFmpeg produced an invalid or truncated WAV file"
    raise AppError(f"Could not extract a usable audio track: {detail}")
