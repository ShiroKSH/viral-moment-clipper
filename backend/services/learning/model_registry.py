from __future__ import annotations

import json
import logging
import os
import pickle
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib
import sklearn
from sklearn.pipeline import Pipeline

from backend.core.config import Settings
from backend.core.paths import resolve_project_path
from backend.core.utils import utc_now, write_json
from backend.db.database import get_connection
from backend.services.learning.evaluation import MODEL_SPEC_VERSION


logger = logging.getLogger(__name__)


def latest_model_record(*, active_only: bool = False) -> dict[str, Any] | None:
    try:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT version, model_path, training_rows, metrics_json, active FROM ranking_models "
                "WHERE (? = 0 OR active = 1) ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (int(active_only),),
            ).fetchone()
        if not row:
            return None
        metrics = json.loads(row["metrics_json"])
        if not isinstance(metrics, dict):
            return None
        return {**dict(row), "metrics": metrics}
    except (sqlite3.Error, ValueError, TypeError):
        return None


@lru_cache(maxsize=1)
def _load_model(path: str, modified_ns: int, size: int) -> Pipeline:
    # Only application-created local artifacts are registered; joblib is not an import format.
    return joblib.load(path)


def active_model() -> tuple[Pipeline, dict[str, Any]] | None:
    record = latest_model_record(active_only=True)
    if not record:
        return None
    metrics = record["metrics"]
    validation = metrics.get("validation", {})
    if (
        metrics.get("model_spec_version") != MODEL_SPEC_VERSION
        or metrics.get("sklearn_version") != sklearn.__version__
        or not isinstance(validation, dict)
        or validation.get("passed") is not True
    ):
        return None
    try:
        path = Path(record["model_path"])
        stat = path.stat()
        model = _load_model(str(path), stat.st_mtime_ns, stat.st_size)
        if not isinstance(model, Pipeline) or list(model.classes_) != [0, 1]:
            return None
        return model, record
    except (OSError, ValueError, EOFError, ImportError, pickle.UnpicklingError, AttributeError, IndexError, KeyError, TypeError):
        logger.warning("Personal ranker %s is unreadable; using online preferences.", record["version"])
        return None


def deactivate_models() -> None:
    with get_connection() as connection:
        connection.execute("UPDATE ranking_models SET active = 0 WHERE active = 1")


def save_model(model: Pipeline, config: Settings, rows: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    created_at = utc_now()
    version = f"personal_ranker_{created_at.replace('-', '').replace(':', '').replace('.', '')}_{uuid4().hex[:8]}"
    directory = resolve_project_path(config.paths.models_dir) / "ranking_models"
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / f"{version}.joblib"
    sidecar_path = directory / f"{version}.json"
    temporary_path = directory / f".{version}.tmp"
    try:
        joblib.dump(model, temporary_path)
        os.replace(temporary_path, model_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    active = metrics["validation"]["passed"]
    metrics = {**metrics, "model_path": str(model_path), "sidecar_path": str(sidecar_path)}
    sidecar = {
        "version": version,
        "model_path": str(model_path),
        "created_at": created_at,
        "training_rows": len(rows),
        "positive_count": sum(row["label"] == 1 for row in rows),
        "negative_count": sum(row["label"] == 0 for row in rows),
        "active": active,
        "metrics": metrics,
    }
    if config.learning.save_training_rows:
        sidecar["examples"] = [
            {key: row.get(key) for key in ("project_id", "moment_id", "clip_id", "label", "features", "retention_percent")}
            for row in rows
        ]
    write_json(sidecar_path, sidecar)
    with get_connection() as connection:
        connection.execute("UPDATE ranking_models SET active = 0 WHERE active = 1")
        connection.execute(
            """
            INSERT INTO ranking_models (id, version, model_path, training_rows, metrics_json, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid4().hex, version, str(model_path), len(rows), json.dumps(metrics, allow_nan=False), created_at, int(active)),
        )
    _load_model.cache_clear()
    return {
        "trained": True,
        "active": active,
        "version": version,
        "active_ranker_version": version if active else "online_preference_v002",
        "model_path": str(model_path),
        "sidecar_path": str(sidecar_path),
        "metrics": metrics,
    }
