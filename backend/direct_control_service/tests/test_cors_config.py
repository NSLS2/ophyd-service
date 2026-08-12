"""CORS config resolution for the module-level app (security regression tests).

resolve_cors_config() is read at import time (the app adds CORSMiddleware before
the lifespan Settings exist). It must force credentials off whenever a wildcard
origin is configured — wildcard + credentials lets any site drive credentialed
cross-origin requests.
"""

from direct_control.config import resolve_cors_config


def test_default_is_wildcard_without_credentials(monkeypatch):
    monkeypatch.delenv("DIRECT_CONTROL_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("DIRECT_CONTROL_CORS_ALLOW_CREDENTIALS", raising=False)
    assert resolve_cors_config() == (["*"], False)


def test_wildcard_forces_credentials_off(monkeypatch):
    monkeypatch.setenv("DIRECT_CONTROL_CORS_ORIGINS", '["*"]')
    monkeypatch.setenv("DIRECT_CONTROL_CORS_ALLOW_CREDENTIALS", "true")
    assert resolve_cors_config() == (["*"], False)


def test_explicit_origins_allow_credentials(monkeypatch):
    monkeypatch.setenv("DIRECT_CONTROL_CORS_ORIGINS", '["https://ui.example"]')
    monkeypatch.setenv("DIRECT_CONTROL_CORS_ALLOW_CREDENTIALS", "true")
    assert resolve_cors_config() == (["https://ui.example"], True)


def test_explicit_origins_default_no_credentials(monkeypatch):
    monkeypatch.setenv("DIRECT_CONTROL_CORS_ORIGINS", '["https://ui.example"]')
    monkeypatch.delenv("DIRECT_CONTROL_CORS_ALLOW_CREDENTIALS", raising=False)
    assert resolve_cors_config() == (["https://ui.example"], False)
