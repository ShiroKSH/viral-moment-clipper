from backend.services.analysis_artifacts import archive_analysis_artifacts


def test_archive_moves_only_previous_generation_artifacts(tmp_path):
    clip_id = "clip_03_deadbeef_project"
    clip_path = tmp_path / "clips" / f"{clip_id}_score_88.mp4"
    subtitle_path = tmp_path / "subtitles" / f"{clip_id}.ass"
    metadata_path = tmp_path / "metadata" / f"{clip_id}_edit_plan.json"
    report_path = tmp_path / "source" / "analysis_report.json"
    source_path = tmp_path / "source" / "source.mp4"
    for path in (clip_path, subtitle_path, metadata_path, report_path, source_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"artifact")

    result = archive_analysis_artifacts(tmp_path, [clip_id])

    assert result.archive_dir is not None
    assert not clip_path.exists()
    assert not subtitle_path.exists()
    assert not metadata_path.exists()
    assert not report_path.exists()
    assert source_path.exists()
    assert (result.archive_dir / "clips" / clip_path.name).exists()
    assert (result.archive_dir / "manifest.json").exists()
    assert "clips/" + clip_path.name in result.moved_files


def test_archive_rejects_unsafe_clip_ids(tmp_path):
    outside = tmp_path.parent / "clip_escape_score_99.mp4"
    outside.write_bytes(b"keep")

    result = archive_analysis_artifacts(tmp_path, ["clip_../../escape"])

    assert outside.exists()
    assert result.archive_dir is None
    assert result.warnings == ["Skipped unsafe clip id: 'clip_../../escape'"]
