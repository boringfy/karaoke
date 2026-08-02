from __future__ import annotations

import pytest

from karaoke_server import config


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Isolated settings pointing at a temp data dir."""
    monkeypatch.setenv("KARAOKE_DATA_DIR", str(tmp_path / "data"))
    config.get_settings.cache_clear()
    s = config.get_settings()
    s.ensure_dirs()
    yield s
    config.get_settings.cache_clear()
