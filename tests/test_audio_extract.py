import json
import subprocess
import wave
from pathlib import Path

import pytest

from backend.core.config import Settings
from backend.core.errors import AppError
from backend.services import audio_extract


def _write_wav(path, duration: float) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(audio_extract.SAMPLE_RATE)
        output.writeframes(b"\0\0" * round(duration * audio_extract.SAMPLE_RATE))


def _probe_payload(video: float, audio: float, container: float) -> dict:
    return {
        "streams": [
            {"codec_type": "video", "duration": str(video)},
            {"codec_type": "audio", "duration": str(audio)},
        ],
        "format": {"duration": str(container)},
    }


def test_extract_wav_caps_corrupt_audio_to_video_and_preserves_timeline(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(audio_extract, "ffprobe_json", lambda *_: _probe_payload(10.0, 20.0, 20.0))

    def fake_run(argv, timeout=None):
        calls.append(argv)
        _write_wav(argv[-1], 10.0)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="decoder warning\n")

    monkeypatch.setattr(audio_extract, "run_command", fake_run)
    output = tmp_path / "audio.wav"

    result = audio_extract.extract_wav(tmp_path / "source.mp4", output, Settings())

    assert result == output
    assert audio_extract.wav_duration(output) == pytest.approx(10.0)
    assert calls[0][calls[0].index("-t") + 1] == "10.000"
    assert "aresample=async=1000:first_pts=0,apad=whole_dur=10.000" in calls[0]
    report = json.loads(audio_extract.audio_extraction_report_path(output).read_text(encoding="utf-8"))
    assert report["mode"] == "recovered_decoder_errors"
    assert report["duration_source"] == "video"
    assert report["source_durations"]["audio"] == 20.0


def test_extract_wav_retries_with_corrupt_packet_recovery(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(audio_extract, "ffprobe_json", lambda *_: _probe_payload(4.0, 4.0, 4.0))

    def fake_run(argv, timeout=None):
        calls.append(argv)
        if len(calls) == 1:
            raise AppError("strict decode failed")
        _write_wav(argv[-1], 4.0)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(audio_extract, "run_command", fake_run)
    output = tmp_path / "audio.wav"

    audio_extract.extract_wav(tmp_path / "source.mp4", output, Settings())

    assert len(calls) == 2
    assert "+discardcorrupt" in calls[1]
    assert "ignore_err" in calls[1]
    report = json.loads(audio_extract.audio_extraction_report_path(output).read_text(encoding="utf-8"))
    assert report["mode"] == "recovery"


def test_extract_wav_keeps_previous_output_when_recovery_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_extract, "ffprobe_json", lambda *_: _probe_payload(10.0, 10.0, 10.0))
    monkeypatch.setattr(audio_extract, "run_command", lambda *_args, **_kwargs: (_ for _ in ()).throw(AppError("broken AAC")))
    output = tmp_path / "audio.wav"
    _write_wav(output, 3.0)

    with pytest.raises(AppError, match="Could not extract a usable audio track"):
        audio_extract.extract_wav(tmp_path / "source.mp4", output, Settings())

    assert audio_extract.wav_duration(output) == pytest.approx(3.0)
