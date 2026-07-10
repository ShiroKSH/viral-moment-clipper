import json

from backend.core.config import Settings
from backend.services import project_store, video_probe


def test_probe_video_uses_playable_video_duration(monkeypatch, tmp_path):
    monkeypatch.setattr(
        video_probe,
        "ffprobe_json",
        lambda *_: {
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "1427.04",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "25/1",
                    "codec_name": "h264",
                },
                {"codec_type": "audio", "duration": "1958.57", "codec_name": "aac"},
            ],
            "format": {"duration": "1958.57"},
        },
    )

    metadata = video_probe.probe_video(tmp_path / "source.mp4", Settings())

    assert metadata.duration == 1427.04
    assert metadata.audio_codec == "aac"


def test_stored_video_metadata_uses_playable_duration():
    raw = {
        "streams": [
            {"codec_type": "video", "duration": "1427.04"},
            {"codec_type": "audio", "duration": "1958.57"},
        ],
        "format": {"duration": "1958.57"},
    }
    row = {
        "duration": 1958.57,
        "width": 1920,
        "height": 1080,
        "fps": 25,
        "video_codec": "h264",
        "audio_codec": "aac",
        "metadata_json": json.dumps({"duration": 1958.57, "raw": raw}),
    }

    metadata = project_store._video_from_row(row)

    assert metadata is not None
    assert metadata.duration == 1427.04
    assert metadata.raw == raw
