"""SQLite engine, session, and schema bootstrap.

Import every table class here so SQLModel.metadata is complete before
create_all. DATABASE_URL env overrides the YAML url via get_config().
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from backend.core.config import get_config
from backend.core.models import (  # noqa: F401
    Account,
    BankMeshSignal,
    CircuitBreakerLog,
    ComprehensionProbe,
    ContextFlag,
    Event,
    PatternSignature,
    RiskDecision,
    ScopedHold,
    Transaction,
    TrustedContact,
)

_config = get_config()
_database_url = _config["database"]["url"]

_connect_args: dict = {}
if _database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    _database_url,
    echo=False,
    connect_args=_connect_args,
)


@event.listens_for(engine, "connect")
def _sqlite_on_connect(dbapi_conn, _connection_record) -> None:
    # journal_mode=WAL persists on the file; foreign_keys is per connection.
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


if _database_url.startswith("sqlite"):
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.commit()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
