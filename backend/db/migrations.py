from backend.db.database import init_db


def migrate() -> None:
    init_db()
