"""SQLAlchemy engine, session factory, Base, and get_db dependency."""

from sqlalchemy import event, create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from core.config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},  # Required for SQLite
        echo=False,
    )
else:
    # Postgres (e.g. Supabase). pool_pre_ping revalidates connections the
    # pooler may have dropped; pool_recycle stays under Supabase's idle
    # timeout so we never hand out a dead connection.
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False,
    )


if _is_sqlite:
    # Enable foreign key enforcement for every SQLite connection
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
