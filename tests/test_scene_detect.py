from types import SimpleNamespace

from backend.services import scene_detect


def test_scene_parser_keeps_early_cut_and_drops_near_duplicates():
    stderr = "pts_time:0.36 pts_time:6.64 pts_time:6.72 pts_time:12.80 pts_time:14.90"

    assert scene_detect._parse_scene_times(stderr, 15.13) == [0.36, 6.64, 12.8]


def test_scene_detection_uses_cuda_then_returns_relative_cuts(monkeypatch, tmp_path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    commands: list[list[str]] = []

    def fake_run(command: list[str], timeout: int):
        commands.append(command)
        return SimpleNamespace(stderr="pts_time:0.20\npts_time:4.25\npts_time:9.10")

    monkeypatch.setattr(scene_detect, "run_command", fake_run)

    cuts = scene_detect.detect_scene_cuts(
        video,
        ffmpeg_path="ffmpeg",
        start=120.0,
        duration=12.0,
        threshold=0.10,
        hwaccel="cuda",
    )

    assert cuts == [0.2, 4.25, 9.1]
    assert commands[0][:7] == ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-hwaccel", "cuda"]
    assert "setpts=PTS-STARTPTS,select=gt(scene\\,0.100),showinfo" in commands[0]
