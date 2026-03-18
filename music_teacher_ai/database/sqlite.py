from sqlmodel import SQLModel, Session, create_engine
from music_teacher_ai.config.settings import DATABASE_PATH


DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{DATABASE_PATH}", echo=False)


def create_db():
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
