import sqlite3

import pytest

from backend.db import database


def test_connection_context_commits_and_closes_database(monkeypatch, tmp_path):
    database_path = tmp_path / "app.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    database.init_db()

    with database.get_connection() as connection:
        connection.execute(
            """
            INSERT INTO projects (id, name, output_dir, created_at, status)
            VALUES ('project', 'Project', 'output/project', '2026-08-11', 'created')
            """
        )

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")

    renamed_path = database_path.with_name("renamed.sqlite3")
    database_path.replace(renamed_path)
    assert renamed_path.exists()
