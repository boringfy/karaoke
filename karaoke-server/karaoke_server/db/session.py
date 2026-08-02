from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _configure_sqlite(dbapi_conn, _record) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_engine(db_path: Path | str) -> AsyncEngine:
    global _engine, _sessionmaker
    url = f"sqlite+aiosqlite:///{db_path}" if db_path != ":memory:" else "sqlite+aiosqlite://"
    _engine = create_async_engine(url)
    event.listen(_engine.sync_engine, "connect", _configure_sqlite)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _migrate_missing_columns(sync_conn) -> None:
    """Additive micro-migration: add any model columns missing from existing
    tables (databases created before the column existed). create_all() only
    creates missing *tables*, so upgrades need this. Only nullable columns and
    columns with a server default can be added to a SQLite table; anything else
    is a real schema migration and should fail loudly instead."""
    inspector = inspect(sync_conn)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            if not col.nullable and col.server_default is None:
                raise RuntimeError(
                    f"cannot auto-migrate NOT NULL column "
                    f"{table.name}.{col.name}; migrate the database manually"
                )
            ddl = (
                f"ALTER TABLE {table.name} ADD COLUMN {col.name} "
                f"{col.type.compile(sync_conn.dialect)}"
            )
            if col.server_default is not None:
                ddl += f" DEFAULT {col.server_default.arg}"
            sync_conn.exec_driver_sql(ddl)


async def create_all() -> None:
    assert _engine is not None, "init_engine() first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_missing_columns)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    assert _sessionmaker is not None, "init_engine() first"
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_factory()() as session:
        yield session


async def claim_immediate(session: AsyncSession) -> None:
    """Begin an IMMEDIATE transaction so concurrent workers can't double-claim jobs."""
    await session.execute(text("BEGIN IMMEDIATE"))
