"""Shared fixtures for Harle integration tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from harle.db.connection import Database
from harle.db.models import Conversation, Message


@pytest.fixture
def chat_db() -> Database:
    """In-memory SQLite DB with conversation and message tables for chat tests."""
    db = Database.__new__(Database)
    db.engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    Conversation.__table__.create(db.engine, checkfirst=True)
    Message.__table__.create(db.engine, checkfirst=True)
    return db
