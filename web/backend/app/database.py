"""Database engine, sessions, and migration bootstrap."""

from __future__ import annotations

from collections.abc import Generator

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.paths import BACKEND_DIR, DATABASE_PATH, ensure_data_directories


class Base(DeclarativeBase):
    """Declarative model base."""


engine: Engine = create_engine(
    f"sqlite:///{DATABASE_PATH.as_posix()}",
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@event.listens_for(engine, "connect")
def configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
    """Enable SQLite safety and concurrency pragmas for every connection."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def run_migrations() -> None:
    """Upgrade the configured database to the latest Alembic revision."""
    ensure_data_directories()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{DATABASE_PATH.as_posix()}")
    command.upgrade(config, "head")


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
