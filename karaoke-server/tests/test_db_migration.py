"""create_all() must upgrade databases created before newer columns existed."""

from __future__ import annotations

from sqlalchemy import text

from karaoke_server.db import session as db


async def test_missing_column_is_added_on_startup(tmp_path):
    db_path = tmp_path / "karaoke.db"

    # Fresh schema, then simulate an old database by dropping a newer column.
    db.init_engine(db_path)
    await db.create_all()
    engine = db._engine
    assert engine is not None
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE songs DROP COLUMN cover_path"))
        await conn.execute(text("ALTER TABLE songs DROP COLUMN subtitle_offset_ms"))
    await db.dispose_engine()

    # Re-init (as on server startup): the column must come back.
    db.init_engine(db_path)
    await db.create_all()
    async with db.session_factory()() as session:
        row = (
            await session.execute(
                text("SELECT cover_path, subtitle_offset_ms FROM songs LIMIT 1")
            )
        ).first()
        assert row is None  # empty table, but the columns exist and are queryable

        # The defaulted column must backfill existing rows with 0, not NULL.
        await session.execute(
            text(
                "INSERT INTO songs (id, language, status, created_at, updated_at) "
                "VALUES ('x', 'unknown', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        val = (
            await session.execute(
                text("SELECT subtitle_offset_ms FROM songs WHERE id = 'x'")
            )
        ).scalar_one()
        assert val == 0
    await db.dispose_engine()
