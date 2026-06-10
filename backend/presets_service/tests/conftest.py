"""Pytest fixtures for Presets Service tests."""

import pytest
from fastapi.testclient import TestClient

from presets_service.main import create_app
from presets_service.settings import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=tmp_path / "test_presets.db")


@pytest.fixture
def seeded_settings(tmp_path) -> Settings:
    """Settings pointing at the repo's seed directory."""
    import pathlib

    seed_dir = pathlib.Path(__file__).resolve().parents[3] / "integration" / "presets"
    return Settings(db_path=tmp_path / "test_presets.db", seed_path=seed_dir)


@pytest.fixture
def client(settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def seeded_client(seeded_settings) -> TestClient:
    app = create_app(seeded_settings)
    with TestClient(app) as c:
        yield c
