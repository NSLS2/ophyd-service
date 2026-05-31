"""
Pytest fixtures for Configuration Service tests.

All tests use mock data — no external profile collections required — but they DO
require a reachable PostgreSQL instance (the service is Postgres-only). Point
TEST_DATABASE_URL at one, e.g.:

    docker run --rm -d -p 5432:5432 \
        -e POSTGRES_USER=bluesky -e POSTGRES_PASSWORD=bluesky -e POSTGRES_DB=config_service \
        postgres:16
    export TEST_DATABASE_URL=postgresql+psycopg://bluesky:bluesky@localhost:5432/config_service

CI provides this via a `postgres` service container. Each test gets a clean
schema: the fixture drops and recreates all tables before the app starts, so the
lifespan re-seeds from mock data every time.
"""

import os

import pytest
from fastapi.testclient import TestClient

from configuration_service.config import Settings
from configuration_service.db import make_engine, metadata
from configuration_service.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://bluesky:bluesky@localhost:5432/config_service",
)


@pytest.fixture
def pg_url() -> str:
    """A clean test database: drop + recreate all tables, return the DSN.

    Use in ``Settings(database_url=pg_url)``. Each test starts from an empty
    schema; the app lifespan re-seeds from mock data on startup.
    """
    engine = make_engine(TEST_DATABASE_URL)
    try:
        metadata.drop_all(engine)
        metadata.create_all(engine)
    finally:
        engine.dispose()
    return TEST_DATABASE_URL


@pytest.fixture
def pg_engine(pg_url):
    """An Engine on the clean test database, for tests that drive a store directly."""
    engine = make_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def mock_settings(pg_url) -> Settings:
    """Settings configured for mock data against the clean test PostgreSQL."""
    return Settings(use_mock_data=True, database_url=pg_url)


@pytest.fixture
def mock_client(mock_settings) -> TestClient:
    """Test client with mock data."""
    app = create_app(mock_settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client(mock_settings) -> TestClient:
    """Default test client (mock data)."""
    app = create_app(mock_settings)
    with TestClient(app) as client:
        yield client
