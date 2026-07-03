from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tron_tracer.config import DEFAULT_DB_URL
from tron_tracer.db.models import Base


def make_engine(db_url: str = DEFAULT_DB_URL, *, echo: bool = False):
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, echo=echo, connect_args=connect_args)
    return engine


def init_db(db_url: str = DEFAULT_DB_URL, *, echo: bool = False):
    engine = make_engine(db_url, echo=echo)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(db_url: str = DEFAULT_DB_URL, *, echo: bool = False) -> Iterator[Session]:
    engine = init_db(db_url, echo=echo)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
