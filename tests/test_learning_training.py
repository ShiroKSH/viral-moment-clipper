import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend import main
from backend.db import database
from backend.main import create_app
from backend.schemas.clips import ClipCandidate
from backend.schemas.feedback import FeedbackRequest, MetricsRequest
from backend.schemas.moments import InterestingMoment
from backend.services import project_store
from backend.services.learning import dataset, model_registry, personal_ranker, training
from backend.services.learning.feedback_store import store_feedback
from backend.services.learning.metrics_import import store_metrics


@pytest.fixture
def learning_setup(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "learning.sqlite3")
    database.init_db()
    settings = Settings.model_validate({
        "paths": {"models_dir": str(tmp_path / "models"), "output_dir": str(tmp_path / "output"), "temp_dir": str(tmp_path / "temp")},
        "learning": {"min_feedback_before_training": 4},
    })
    collecting = settings.model_copy(deep=True)
    collecting.learning.enabled = False
    with database.get_connection() as connection:
        for index in range(2):
            connection.execute(
                "INSERT INTO projects (id, name, output_dir, created_at, status) VALUES (?, ?, ?, ?, ?)",
                (f"project_{index}", f"Project {index}", str(tmp_path / str(index)), "2026-01-01", "ready"),
            )
    for index in range(4):
        project_id = f"project_{index % 2}"
        moment = InterestingMoment(
            id=f"moment_{index}", start=0, end=20, duration=20,
            text="A useful idea", summary="Summary", hook_text="Hook",
            moment_type="insight" if index < 2 else "personal_story",
            base_score=85 if index < 2 else 30,
        )
        project_store.save_moment(project_id, moment)
        project_store.save_clip(project_id, ClipCandidate(
            id=f"clip_{index}", moment_id=moment.id, start=0, end=20, duration=20,
            final_score=moment.base_score, base_score=moment.base_score,
            moment_type=moment.moment_type, hook_text=moment.hook_text, summary=moment.summary,
            reason=moment.reason, text=moment.text,
            suggested_title=moment.suggested_title, suggested_caption=moment.suggested_caption,
        ))
        store_feedback(project_id, f"clip_{index}", moment.id, FeedbackRequest(
            action="accept" if index < 2 else "reject",
        ), collecting)
        store_metrics(f"clip_{index}", MetricsRequest(
            platform="test", retention_percent=70 + index, avg_watch_time_sec=12 + index, views=1000 + index,
        ))
    store_feedback("project_0", "old_clip", "old_moment", FeedbackRequest(action="reject"), collecting)
    monkeypatch.setattr(training, "load_config", lambda: settings)
    monkeypatch.setattr(personal_ranker, "load_config", lambda: settings)
    monkeypatch.setattr(main, "load_config", lambda: settings)
    return settings


def test_training_persists_activates_and_predicts_with_local_model(learning_setup):
    result = training.train_personal_ranker(learning_setup)

    assert result["trained"] is True
    assert result["active"] is True
    assert result["training_rows"] == 4
    assert result["retention"]["samples_with_retention"] == 4
    assert Path(result["model_path"]).exists()
    sidecar = json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))
    assert sidecar["metrics"]["average_retention_percent"] == 71.5
    validation = sidecar["metrics"]["validation"]
    assert validation["passed"]
    assert validation["brier_score"] < validation["baseline_brier_score"]
    assert len(sidecar["examples"]) == 4
    for fold in validation["fold_reports"]:
        assert set(fold["training_projects"]).isdisjoint(fold["validation_projects"])
    model, record = model_registry.active_model()
    assert record["version"] == result["active_ranker_version"]
    assert model.predict_proba([{"moment_type": "insight", "base_score": 85}])[0][1] > 0.5


def test_latest_feedback_uses_moment_id_and_ignores_detached_features(learning_setup):
    rows = dataset.latest_feedback_rows()
    assert len(rows) == 5
    assert len(dataset.labeled_training_rows(rows)) == 4


def test_training_uses_immutable_feature_snapshot(learning_setup):
    with database.get_connection() as connection:
        connection.execute(
            "UPDATE feedback SET features_json = ? WHERE moment_id = 'moment_0'",
            ('{"moment_type":"snapshot_type","base_score":22,"speaker_count":2,"speaker_switches":4,"dialogue_score":75}',),
        )
        connection.execute("UPDATE moments SET base_score = 99, source_json = '{}' WHERE id = 'moment_0'")
    row = next(row for row in dataset.labeled_training_rows() if row["candidate_id"] == "moment_0")
    assert row["features"]["moment_type"] == "snapshot_type"
    assert row["features"]["base_score"] == 22
    assert row["features"]["speaker_count"] == 2


@pytest.mark.parametrize("snapshot", [
    "broken JSON", "[]", '{"moment_type":null}',
    '{"moment_type":"insight","duration":"broken"}',
    '{"moment_type":"insight","base_score":NaN}',
    '{"moment_type":"insight","word_count":Infinity}',
    '{"moment_type":"insight","base_score":101}',
])
def test_corrupt_snapshot_is_skipped_without_replacing_historical_features(learning_setup, snapshot):
    with database.get_connection() as connection:
        connection.execute("UPDATE feedback SET features_json = ? WHERE moment_id = 'moment_0'", (snapshot,))
    assert len(dataset.labeled_training_rows()) == 3


def test_latest_decision_overrides_history_and_render_events_do_not_train(learning_setup):
    collecting = learning_setup.model_copy(deep=True)
    collecting.learning.enabled = False
    store_feedback("project_0", "clip_0", "moment_0", FeedbackRequest(action="reject"), collecting)
    store_feedback("project_0", "clip_0", "moment_0", FeedbackRequest(action="rendered"), collecting)
    rows = dataset.labeled_training_rows()
    assert len(rows) == 4
    assert next(row for row in rows if row["moment_id"] == "moment_0")["label"] == 0
    assert "insight" not in personal_ranker.preferred_types(rows)


def test_repeated_publication_capture_uses_latest_values_and_preserves_zero(learning_setup):
    store_metrics("clip_0", MetricsRequest(platform="test", retention_percent=0, views=2000))
    rows = dataset.labeled_training_rows()
    row = next(row for row in rows if row["moment_id"] == "moment_0")
    assert row["metric_count"] == 1
    assert row["retention_percent"] == 0
    assert row["views"] == 2000
    assert dataset.retention_summary(rows)["average_retention_percent"] == 54


def test_missing_retention_has_neutral_weight(learning_setup):
    store_metrics("clip_0", MetricsRequest(platform="test", views=5000))
    rows = dataset.labeled_training_rows()
    weights, enabled = dataset.sample_weights(rows, 2)
    row_index = next(index for index, row in enumerate(rows) if row["moment_id"] == "moment_0")
    assert enabled
    assert rows[row_index]["retention_percent"] is None
    assert weights[row_index] == 1.0
    assert dataset.sample_weights(rows, 4) == ([1.0] * 4, False)


def test_repeated_training_is_skipped_but_deleted_artifact_is_rebuilt(learning_setup):
    first = training.train_personal_ranker(learning_setup)
    assert not training.train_personal_ranker(learning_setup)["trained"]
    Path(first["model_path"]).unlink()
    assert training.train_personal_ranker(learning_setup)["trained"]


def test_one_source_project_cannot_activate_model(learning_setup):
    with database.get_connection() as connection:
        connection.execute("UPDATE feedback SET project_id = 'project_0'")
    result = training.train_personal_ranker(learning_setup)
    assert result["trained"]
    assert not result["active"]
    assert result["metrics"]["validation"]["status"] == "insufficient_projects"
    assert model_registry.active_model() is None
    assert not training.train_personal_ranker(learning_setup)["trained"]


def test_uninformative_features_fail_validation_and_deactivate_stale_model(learning_setup):
    training.train_personal_ranker(learning_setup)
    with database.get_connection() as connection:
        connection.execute(
            "UPDATE feedback SET features_json = ? WHERE moment_id != 'old_moment'",
            ('{"moment_type":"insight","base_score":50}',),
        )
    result = training.train_personal_ranker(learning_setup)
    assert result["trained"]
    assert not result["active"]
    assert result["metrics"]["validation"]["status"] == "below_baseline"
    assert model_registry.active_model() is None


def test_model_fingerprint_tracks_data_and_training_config(learning_setup):
    rows = dataset.labeled_training_rows()
    fingerprint = training.training_fingerprint(rows, learning_setup)
    assert training.training_fingerprint(list(reversed(rows)), learning_setup) == fingerprint
    rows[0]["created_at"] = "2099-01-01"
    assert training.training_fingerprint(rows, learning_setup) == fingerprint
    learning_setup.learning.min_metrics_before_training += 1
    assert training.training_fingerprint(rows, learning_setup) != fingerprint


def test_training_rows_can_be_omitted_from_sidecar(learning_setup):
    learning_setup.learning.save_training_rows = False
    result = training.train_personal_ranker(learning_setup)
    assert "examples" not in json.loads(Path(result["sidecar_path"]).read_text(encoding="utf-8"))


def test_corrupt_model_uses_fallback_and_can_be_retrained(learning_setup):
    first = training.train_personal_ranker(learning_setup)
    assert model_registry.active_model()
    Path(first["model_path"]).write_bytes(b"damaged artifact")
    assert model_registry.active_model() is None
    assert training.train_personal_ranker(learning_setup)["active"]


def test_failed_model_write_does_not_replace_previous_active_model(learning_setup, monkeypatch):
    first = training.train_personal_ranker(learning_setup)
    store_metrics("clip_0", MetricsRequest(platform="test", retention_percent=98))

    def fail_dump(model, path):
        Path(path).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(model_registry.joblib, "dump", fail_dump)
    with pytest.raises(OSError, match="disk full"):
        training.train_personal_ranker(learning_setup)
    assert model_registry.active_model()[1]["version"] == first["version"]
    assert not list(Path(first["model_path"]).parent.glob("*.tmp"))


def test_disabled_training_does_not_load_feedback(monkeypatch):
    settings = Settings()
    settings.learning.enabled = False
    monkeypatch.setattr(dataset, "labeled_training_rows", lambda: pytest.fail("disabled learning read feedback"))
    assert training.train_personal_ranker(settings)["trained"] is False


def test_database_read_failure_does_not_deactivate_existing_model(learning_setup, monkeypatch):
    first = training.train_personal_ranker(learning_setup)

    def unavailable_database():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(dataset, "get_connection", unavailable_database)
    with pytest.raises(sqlite3.OperationalError):
        training.train_personal_ranker(learning_setup)
    assert model_registry.active_model()[1]["version"] == first["version"]


def test_learning_api_trains_real_model_and_reports_validation(learning_setup):
    with TestClient(create_app()) as client:
        response = client.post("/api/learning/train")
        assert response.status_code == 200
        assert response.json()["active"]
        summary = client.get("/api/learning/summary")
        assert summary.status_code == 200
        assert summary.json()["model_active"]
        assert summary.json()["validation"]["method"] == "stratified_group_kfold"
        assert summary.json()["validation"]["passed"]
        positive = project_store.get_moment("project_0", "moment_0")
        negative = project_store.get_moment("project_0", "moment_2")
        ranked = personal_ranker.apply_personal_ranking([negative, positive], learning_setup)
        assert [moment.id for moment in ranked] == ["moment_0", "moment_2"]
        assert ranked[0].personal_score > ranked[1].personal_score


def test_learning_summary_counts_only_latest_decisions_in_accepted_average(learning_setup):
    collecting = learning_setup.model_copy(deep=True)
    collecting.learning.enabled = False
    with database.get_connection() as connection:
        connection.execute("UPDATE moments SET final_score = 90 WHERE id = 'moment_0'")
        connection.execute("UPDATE moments SET final_score = 60 WHERE id = 'moment_1'")
    store_feedback("project_0", "clip_0", "moment_0", FeedbackRequest(action="accept"), collecting)
    with TestClient(create_app()) as client:
        assert client.get("/api/learning/summary").json()["average_score_accepted"] == 75
        store_feedback("project_0", "clip_0", "moment_0", FeedbackRequest(action="reject"), collecting)
        summary = client.get("/api/learning/summary").json()
        assert summary["average_score_accepted"] == 60
        assert summary["accepted_count"] == 1


def test_metrics_endpoint_validates_numbers_and_stores_missing_values(learning_setup):
    with TestClient(create_app()) as client:
        invalid = client.post("/api/clips/clip_0/metrics", json={"platform": "test", "retention_percent": "Infinity"})
        assert invalid.status_code == 422
        saved = client.post("/api/clips/clip_0/metrics", json={"platform": "test", "views": 5000})
        assert saved.status_code == 200
    row = next(row for row in dataset.labeled_training_rows() if row["moment_id"] == "moment_0")
    assert row["retention_percent"] is None
    assert row["avg_watch_time_sec"] is None


def test_nonfinite_legacy_metrics_are_excluded_from_reports(learning_setup):
    with database.get_connection() as connection:
        connection.execute("UPDATE publish_metrics SET avg_watch_time_sec = ?", (float("inf"),))
    rows = dataset.labeled_training_rows()
    assert all(row["avg_watch_time_sec"] is None for row in rows)
    json.dumps(rows, allow_nan=False)


def test_feedback_change_during_training_does_not_publish_stale_model(learning_setup, monkeypatch):
    evaluate = training.evaluate_model

    def evaluate_then_change_feedback(rows, min_metrics):
        report = evaluate(rows, min_metrics)
        with database.get_connection() as connection:
            connection.execute("UPDATE feedback SET action = 'reject' WHERE moment_id = 'moment_0'")
        return report

    monkeypatch.setattr(training, "evaluate_model", evaluate_then_change_feedback)
    assert not training.train_personal_ranker(learning_setup)["trained"]
    assert model_registry.latest_model_record() is None
