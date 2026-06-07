from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine

from app.config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args={"options": f"-c timezone={_settings.timezone}"},
)

SessionLocal = sessionmaker(class_=Session, autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _set_timezone(dbapi_conn, _):
    with dbapi_conn.cursor() as cur:
        cur.execute(f"SET TIME ZONE '{_settings.timezone}'")


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
