from backend.core.config import Settings
from backend.schemas.transcript import Transcript
from backend.services import transcription


def test_transcribe_audio_retries_cpu_int8(monkeypatch, tmp_path):
    calls: list[tuple[str, str]] = []

    def fake_transcribe(audio_path, config, device, compute_type):
        calls.append((device, compute_type))
        if len(calls) == 1:
            raise RuntimeError("cuda unavailable")
        return Transcript(language="ru", duration=1.0, engine=f"faster-whisper:{device}", segments=[], text="")

    monkeypatch.setattr(transcription, "_transcribe_with_faster_whisper", fake_transcribe)
    settings = Settings()
    settings.transcription.device = "cuda"
    settings.transcription.compute_type = "float16"

    result = transcription.transcribe_audio(tmp_path / "audio.wav", settings, duration=12.0)

    assert calls == [("cuda", "float16"), ("cpu", "int8")]
    assert result.engine == "faster-whisper:cpu"
    assert result.duration == 12.0
    assert not transcription.is_synthetic_transcript(result)


def test_transcribe_audio_marks_fallback_as_synthetic(monkeypatch, tmp_path):
    def fail_transcribe(audio_path, config, device, compute_type):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(transcription, "_transcribe_with_faster_whisper", fail_transcribe)

    result = transcription.transcribe_audio(tmp_path / "audio.wav", Settings(), duration=8.0)

    assert result.engine == "fallback"
    assert transcription.is_synthetic_transcript(result)
