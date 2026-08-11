from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from backend.api import routes_projects
from backend.core.config import Settings
from backend.core.errors import AppError
from backend.schemas.video import Project, VideoMetadata


def test_upload_replaces_source_only_after_probe(monkeypatch, tmp_path):
    destination = tmp_path / "source.mp4"
    destination.write_bytes(b"working video")

    def probe_staged_video(path, _config):
        assert path != destination
        assert path.read_bytes() == b"replacement video"
        assert destination.read_bytes() == b"working video"
        return VideoMetadata(
            duration=12,
            width=1920,
            height=1080,
            fps=30,
            raw={"format": {"filename": str(path)}},
        )

    monkeypatch.setattr(routes_projects, "probe_video", probe_staged_video)

    metadata = routes_projects._store_validated_upload(
        BytesIO(b"replacement video"),
        destination,
        Settings(),
    )

    assert metadata.duration == 12
    assert metadata.raw["format"]["filename"] == str(destination)
    assert destination.read_bytes() == b"replacement video"
    assert list(tmp_path.iterdir()) == [destination]


def test_failed_probe_preserves_existing_source(monkeypatch, tmp_path):
    destination = tmp_path / "source.mp4"
    destination.write_bytes(b"working video")

    def reject_video(*_args):
        raise AppError("invalid video")

    monkeypatch.setattr(routes_projects, "probe_video", reject_video)

    with pytest.raises(AppError, match="invalid video"):
        routes_projects._store_validated_upload(
            BytesIO(b"broken upload"),
            destination,
            Settings(),
        )

    assert destination.read_bytes() == b"working video"
    assert list(tmp_path.iterdir()) == [destination]


def test_failed_replacement_upload_restores_project_status(monkeypatch, tmp_path):
    project_id = "upload_test_preserve_status"
    source_path = tmp_path / "source" / "working.mp4"
    project = Project(
        id=project_id,
        name="Existing project",
        output_dir=str(tmp_path),
        source_path=str(source_path),
        created_at="2026-08-11T00:00:00+00:00",
        status="ready",
    )
    status_updates: list[str] = []

    def reject_video(*_args):
        raise AppError("invalid video")

    monkeypatch.setattr(routes_projects.project_store, "get_project", lambda _: project)
    monkeypatch.setattr(
        routes_projects.project_store,
        "set_project_status",
        lambda _project_id, status: status_updates.append(status),
    )
    monkeypatch.setattr(routes_projects, "_store_validated_upload", reject_video)

    with pytest.raises(HTTPException) as exc_info:
        routes_projects.upload_video(
            project_id,
            UploadFile(filename="replacement.mp4", file=BytesIO(b"broken")),
        )

    assert exc_info.value.status_code == 422
    assert status_updates == ["ready"]
