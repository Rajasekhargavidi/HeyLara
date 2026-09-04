"""Database engine/session setup.

Uses SQLAlchemy so the same models run against SQLite for zero-setup local
dev and Postgres in docker-compose — only DATABASE_URL changes.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from packages.config.settings import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from apps.api import models_db  # noqa: F401 - ensure models are registered on Base

    Base.metadata.create_all(bind=engine)
