from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

import sklearn

from backend.core.config import Settings, load_config
from backend.services.learning import dataset, model_registry
from backend.services.learning.evaluation import MODEL_SPEC_VERSION, build_model, evaluate_model
from backend.services.learning.feature_extractor import FEATURE_NAMES


_training_lock = Lock()


def training_fingerprint(rows: list[dict[str, Any]], config: Settings) -> str:
    records = [
        {
            "project_id": row.get("project_id"),
            "candidate_id": row.get("moment_id") or row.get("clip_id") or row.get("candidate_id"),
            "label": row["label"],
            "features": row["features"],
            "retention_percent": dataset.metric_value(row, "retention_percent"),
        }
        for row in rows
    ]
    records.sort(key=lambda row: (str(row["project_id"]), str(row["candidate_id"])))
    payload = {
        "model_spec_version": MODEL_SPEC_VERSION,
        "sklearn_version": sklearn.__version__,
        "min_feedback": config.learning.min_feedback_before_training,
        "min_metrics": config.learning.min_metrics_before_training,
        "save_training_rows": config.learning.save_training_rows,
        "rows": records,
    }
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def train_personal_ranker(config: Settings | None = None) -> dict[str, Any]:
    config = config or load_config()
    if not config.learning.enabled:
        return {"trained": False, "training_ready": False, "active": False, "message": "Learning is disabled."}
    with _training_lock:
        return _train(config)


def _train(config: Settings) -> dict[str, Any]:
    rows = dataset.labeled_training_rows()
    readiness = dataset.training_readiness(rows, config.learning.min_feedback_before_training)
    result: dict[str, Any] = {**readiness, "trained": False, "retention": dataset.retention_summary(rows)}
    if not readiness["training_ready"]:
        model_registry.deactivate_models()
        return {**result, "active": False, "message": "Not enough balanced unique feedback samples for local training."}

    fingerprint = training_fingerprint(rows, config)
    previous = model_registry.latest_model_record()
    if previous and previous["metrics"].get("training_fingerprint") == fingerprint:
        usable = model_registry.active_model() is not None if previous["active"] else Path(previous["model_path"]).is_file()
        if usable:
            return {
                **result,
                "active": bool(previous["active"]),
                "metrics": previous["metrics"],
                "message": "Latest feedback has already been evaluated.",
            }

    validation = evaluate_model(rows, config.learning.min_metrics_before_training)
    weights, weighted = dataset.sample_weights(rows, config.learning.min_metrics_before_training)
    model = build_model()
    model.fit([row["features"] for row in rows], [row["label"] for row in rows], classifier__sample_weight=weights)
    metrics = {
        **dataset.retention_summary(rows),
        "model_spec_version": MODEL_SPEC_VERSION,
        "sklearn_version": sklearn.__version__,
        "training_fingerprint": fingerprint,
        "feature_names": list(FEATURE_NAMES),
        "metric_weighting_active": weighted,
        "validation": validation,
    }
    if training_fingerprint(dataset.labeled_training_rows(), config) != fingerprint:
        return {**result, "message": "Feedback changed during training; this model was not saved."}
    return {**result, **model_registry.save_model(model, config, rows, metrics), "message": validation["message"]}
