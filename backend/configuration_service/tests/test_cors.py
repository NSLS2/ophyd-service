"""CORS middleware wiring (security regression tests).

A wildcard origin combined with credentials makes Starlette reflect the
caller's Origin and echo Access-Control-Allow-Credentials, which would let any
site issue credentialed cross-origin requests. create_app() must force
credentials off whenever cors_origins contains "*". These tests inspect the
middleware config directly (no lifespan/DB needed).
"""

from configuration_service.config import Settings
from configuration_service.main import create_app


def _cors_kwargs(app) -> dict:
    for mw in app.user_middleware:
        if "CORS" in mw.cls.__name__:
            return mw.kwargs
    raise AssertionError("CORS middleware not installed")


def test_default_settings_disable_credentials():
    kw = _cors_kwargs(create_app(Settings()))
    assert kw["allow_origins"] == ["*"]
    assert kw["allow_credentials"] is False


def test_wildcard_origin_forces_credentials_off():
    kw = _cors_kwargs(create_app(Settings(cors_origins=["*"], cors_allow_credentials=True)))
    assert kw["allow_credentials"] is False


def test_explicit_allowlist_permits_credentials():
    kw = _cors_kwargs(
        create_app(Settings(cors_origins=["https://ui.example"], cors_allow_credentials=True))
    )
    assert kw["allow_origins"] == ["https://ui.example"]
    assert kw["allow_credentials"] is True
