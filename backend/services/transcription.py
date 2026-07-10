from __future__ import annotations

import os
from pathlib import Path
import sys

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.schemas.transcript import Transcript, TranscriptSegment, TranscriptWord
from backend.services.transcript_postprocess import repair_transcript_text


FALLBACK_LINES = [
    "В этом фрагменте есть важная мысль, которую можно превратить в короткий клип.",
    "Сначала появляется сильный hook, затем автор объясняет проблему простыми словами.",
    "Дальше есть контраст, личный опыт и понятный вывод для зрителя.",
    "Такой момент может удерживать внимание, потому что он самостоятельный и легко считывается.",
    "Финальная часть звучит как payoff и подходит для короткого вертикального ролика.",
]

_DLL_DIRECTORY_HANDLES = []
_DLL_DIRECTORIES_ADDED: set[str] = set()


def _add_nvidia_dll_directories() -> None:
    if os.name != "nt":
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    for relative in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_nvrtc/bin"):
        dll_dir = site_packages / relative
        if not dll_dir.exists():
            continue
        dll_dir_text = str(dll_dir)
        if dll_dir_text not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir_text + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory") and dll_dir_text not in _DLL_DIRECTORIES_ADDED:
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(dll_dir_text))
            _DLL_DIRECTORIES_ADDED.add(dll_dir_text)


def _fallback_transcript(duration: float, language: str) -> Transcript:
    if duration <= 0:
        duration = 150
    segment_length = max(8.0, min(22.0, duration / max(5, len(FALLBACK_LINES))))
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    index = 0
    while cursor < duration and index < 25:
        text = FALLBACK_LINES[index % len(FALLBACK_LINES)]
        start = cursor
        end = min(duration, start + segment_length)
        words_raw = text.split()
        word_duration = max(0.15, (end - start) / max(1, len(words_raw)))
        words = [
            TranscriptWord(word=word, start=start + i * word_duration, end=min(end, start + (i + 1) * word_duration), probability=None)
            for i, word in enumerate(words_raw)
        ]
        segments.append(TranscriptSegment(id=index + 1, start=start, end=end, text=text, words=words))
        cursor = end + 0.35
        index += 1
    return Transcript(language=language, duration=duration, engine="fallback", segments=segments, text=" ".join(s.text for s in segments))


def is_synthetic_transcript(transcript: Transcript) -> bool:
    return transcript.engine == "fallback"


def _transcribe_with_faster_whisper(audio_path: Path, config: Settings, device: str, compute_type: str) -> Transcript:
    _add_nvidia_dll_directories()
    from faster_whisper import WhisperModel

    model = WhisperModel(config.transcription.model, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=config.transcription.language or None,
        vad_filter=config.transcription.vad_filter,
        word_timestamps=config.transcription.word_timestamps,
    )
    segments: list[TranscriptSegment] = []
    for idx, segment in enumerate(segments_iter, start=1):
        words = [
            TranscriptWord(
                word=word.word.strip(),
                start=float(word.start or segment.start),
                end=float(word.end or segment.end),
                probability=word.probability,
                speaker=getattr(word, "speaker", None),
            )
            for word in (segment.words or [])
            if word.word and word.word.strip()
        ]
        segments.append(
            TranscriptSegment(
                id=idx,
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
                speaker=getattr(segment, "speaker", None),
                words=words,
            )
        )
    text = " ".join(segment.text for segment in segments)
    return Transcript(
        language=info.language or config.transcription.language,
        duration=info.duration,
        engine=f"faster-whisper:{device}",
        segments=segments,
        text=text,
    )


def transcribe_audio(audio_path: Path, config: Settings, duration: float = 0) -> Transcript:
    if config.transcription.engine == "fallback":
        return _fallback_transcript(duration, config.transcription.language)

    attempts: list[tuple[str, str, bool]] = [(config.transcription.device, config.transcription.compute_type, False)]
    primary_is_cpu = config.transcription.device == "cpu"
    if config.transcription.cpu_fallback and not config.transcription.require_gpu and not primary_is_cpu:
        attempts.append(("cpu", config.transcription.fallback_compute_type, True))

    errors: list[str] = []
    for device, compute_type, is_fallback in attempts:
        try:
            transcript = _transcribe_with_faster_whisper(audio_path, config, device, compute_type)
            transcript.duration = duration or transcript.duration
            if is_fallback:
                transcript.engine = f"{transcript.engine}:fallback"
            repair_transcript_text(transcript)
            return transcript
        except Exception as exc:
            errors.append(f"{device}/{compute_type}: {exc}")
            continue

    if config.transcription.require_gpu:
        raise AppError("GPU transcription failed: " + " | ".join(errors))
    if not config.transcription.allow_synthetic_fallback:
        raise AppError("Transcription failed: " + " | ".join(errors))

    transcript = _fallback_transcript(duration, config.transcription.language)
    repair_transcript_text(transcript)
    return transcript
