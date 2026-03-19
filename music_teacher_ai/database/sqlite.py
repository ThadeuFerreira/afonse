import sqlalchemy
from sqlmodel import SQLModel, Session, create_engine
from music_teacher_ai.config.settings import DATABASE_PATH

# Import models so SQLModel.metadata is populated before any DB operation.
import music_teacher_ai.database.models  # noqa: F401, E402

DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)


def _migrate():
    """Add any columns that exist in the models but are missing from the DB.

    SQLite does not support ALTER TABLE … ADD COLUMN IF NOT EXISTS, so we
    check the current schema via PRAGMA table_info and issue one ALTER per
    missing column.  This keeps existing databases in sync when new fields are
    added to models without requiring a full rebuild.
    """
    with engine.connect() as conn:
        for table in SQLModel.metadata.sorted_tables:
            # Skip tables that don't exist yet — create_db() will create them.
            exists = conn.execute(
                sqlalchemy.text(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"
                ),
                {"name": table.name},
            ).first()
            if not exists:
                continue

            result = conn.execute(sqlalchemy.text(f"PRAGMA table_info({table.name})"))
            existing = {row[1] for row in result}  # row[1] is the column name

            for column in table.columns:
                if column.name not in existing:
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(
                        sqlalchemy.text(
                            f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                        )
                    )
            conn.commit()


def create_db():
    SQLModel.metadata.create_all(engine)
    _migrate()


def get_session() -> Session:
    return Session(engine)


# Run on every startup so existing databases stay in sync with model changes
# even when create_db() is not called (e.g. running search or enrich commands).
if DATABASE_PATH.exists():
    try:
        _migrate()
    except Exception:
        pass  # Tables may not exist yet; create_db() will handle creation.
