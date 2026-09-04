import numpy as np
import pytest
from pydantic import ValidationError

from backend.schemas.feedback import MetricsRequest
from backend.schemas.learning import ClipFeatures
from backend.services.learning import evaluation


def _rows():
    return [
        {
            "project_id": f"project_{project}", "label": label,
            "features": ClipFeatures(moment_type="insight", speaker_switches=label * 5, word_count=10 + project * 1000).as_row(),
        }
        for project in range(6)
        for label in (0, 1)
    ]


def test_scaling_is_fitted_inside_each_training_fold(monkeypatch):
    rows = _rows()
    models = []
    build_model = evaluation.build_model

    def record_model():
        model = build_model()
        models.append(model)
        return model

    monkeypatch.setattr(evaluation, "build_model", record_model)
    report = evaluation.evaluate_model(rows, 8)
    assert report["passed"]
    splits = evaluation.validation_splits(rows)
    for model, (train, test) in zip(models, splits):
        names = list(model.named_steps["features"].get_feature_names_out())
        word_count_index = names.index("word_count")
        assert model.named_steps["scale"].mean_[word_count_index] == pytest.approx(
            np.mean([rows[index]["features"]["word_count"] for index in train])
        )
        assert {rows[index]["project_id"] for index in train}.isdisjoint(
            {rows[index]["project_id"] for index in test}
        )
    assert sorted(index for _, test in splits for index in test) == list(range(len(rows)))


def test_project_and_label_confounded_data_is_not_validated_by_random_clip_split():
    rows = _rows()
    for row in rows:
        row["project_id"] = f"class_{row['label']}"
    report = evaluation.evaluate_model(rows, 8)
    assert report["status"] == "insufficient_projects"
    assert not report["passed"]


def test_unknown_project_ids_do_not_fall_back_to_leaky_random_split():
    rows = _rows()
    rows[0]["project_id"] = None
    assert not evaluation.evaluate_model(rows, 8)["passed"]


def test_metrics_distinguish_missing_and_zero_retention():
    assert MetricsRequest(platform="test").retention_percent is None
    assert MetricsRequest(platform="test", retention_percent=0).retention_percent == 0
    with pytest.raises(ValidationError):
        MetricsRequest(platform="test", avg_watch_time_sec=float("inf"))
