"""PostgreSQL connection and session management.

Provides the :class:`Database` helper that wraps a SQLAlchemy engine
and session factory, plus a context-manager for safe session handling.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from harle.db.models import Base

logger = logging.getLogger(__name__)


class Database:
    """Thin wrapper around SQLAlchemy engine and session factory.

    Args:
        database_url: PostgreSQL connection string
            (e.g. ``postgresql+psycopg2://user:pass@localhost:5432/harle``).
    """

    def __init__(self, database_url: str) -> None:
        self.engine: Engine = create_engine(
            database_url,
            pool_pre_ping=True,
            echo=False,
        )
        self._session_factory: sessionmaker[Session] = sessionmaker(
            bind=self.engine,
        )
        logger.info("Database engine created for %s", database_url.split("@")[-1])

    def create_tables(self) -> None:
        """Create all tables defined in :mod:`harle.db.models`.

        Safe to call multiple times — existing tables are not recreated.
        """
        Base.metadata.create_all(self.engine)
        logger.info("Database tables created (or already exist).")

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Provide a transactional session scope.

        Commits on clean exit, rolls back on exception, and always
        closes the session.

        Yields:
            An active SQLAlchemy :class:`Session`.
        """
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
