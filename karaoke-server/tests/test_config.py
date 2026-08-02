from karaoke_server import config


def _fresh(monkeypatch, value):
    monkeypatch.setenv("KARAOKE_CORS_ORIGINS", value)
    config.get_settings.cache_clear()
    try:
        return config.get_settings()
    finally:
        config.get_settings.cache_clear()


def test_cors_default(monkeypatch):
    monkeypatch.delenv("KARAOKE_CORS_ORIGINS", raising=False)
    config.get_settings.cache_clear()
    s = config.get_settings()
    config.get_settings.cache_clear()
    assert "http://localhost:5173" in s.cors_origins


def test_cors_comma_separated_env(monkeypatch):
    s = _fresh(monkeypatch, "http://a.local, https://b.local ,http://c.local")
    assert s.cors_origins == ["http://a.local", "https://b.local", "http://c.local"]


def test_cors_wildcard(monkeypatch):
    s = _fresh(monkeypatch, "*")
    assert s.cors_origins == ["*"]


def test_cors_single(monkeypatch):
    s = _fresh(monkeypatch, "http://only.local")
    assert s.cors_origins == ["http://only.local"]
