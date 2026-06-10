"""Integration tests for the Presets Service API."""

import pytest


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestScanPresetsCRUD:
    """CRUD on /api/v1/scan-presets."""

    _payload = {
        "edge_index": "Fe_L",
        "start": 700.0,
        "stop": 740.0,
        "velocity": 0.1,
        "deadband": 0.05,
        "epu1offset": 0.0,
        "epu_table": 4,
        "scan_count": 1,
        "intervals": 100,
        "au_mesh": 0.0,
        "e_align": 0.0,
        "m1b1_sp": 0.0,
    }

    def test_create_and_get(self, client):
        r = client.post("/api/v1/scan-presets", json=self._payload)
        assert r.status_code == 201
        r = client.get("/api/v1/scan-presets/Fe_L")
        assert r.status_code == 200
        assert r.json()["scan_count"] == 1

    def test_update_partial(self, client):
        client.post("/api/v1/scan-presets", json=self._payload)
        r = client.put("/api/v1/scan-presets/Fe_L", json={"scan_count": 5})
        assert r.json()["scan_count"] == 5
        assert r.json()["velocity"] == 0.1  # unchanged


class TestDetectorPresetsCRUD:
    """CRUD on /api/v1/detector-presets."""

    _payload = {
        "edge_index": "Fe_L",
        "samplegain": "5",
        "sampledecade": "nA",
        "aumeshgain": "5",
        "aumeshdecade": "nA",
        "pd_gain": "5",
        "pd_decade": "nA",
        "vortex_low": 100,
        "vortex_high": 900,
        "ipfy_low": 50,
        "ipfy_high": 800,
        "vortex_pos": 0.0,
        "vortex_time": 1.0,
        "sclr_time": 0.5,
    }

    def test_create_and_get(self, client):
        r = client.post("/api/v1/detector-presets", json=self._payload)
        assert r.status_code == 201
        r = client.get("/api/v1/detector-presets/Fe_L")
        assert r.status_code == 200
        assert r.json()["samplegain"] == "5"


class TestFullPreset:
    """GET /api/v1/edges/{edge_index}/full — combined view."""

    def test_full_not_found(self, client):
        r = client.get("/api/v1/edges/Nope/full")
        assert r.status_code == 404

    def test_full_partial(self, client):
        """Only scan populated — detector is null."""
        client.post(
            "/api/v1/scan-presets",
            json={
                "edge_index": "Cu_L",
                "start": 920.0,
                "stop": 970.0,
                "velocity": 0.1,
                "deadband": 0.05,
                "epu1offset": 0.0,
                "epu_table": 2,
                "scan_count": 1,
                "intervals": 100,
                "au_mesh": 0.0,
                "e_align": 0.0,
                "m1b1_sp": 0.0,
            },
        )
        r = client.get("/api/v1/edges/Cu_L/full")
        assert r.status_code == 200
        data = r.json()
        assert data["edge_index"] == "Cu_L"
        assert data["scan"] is not None
        assert data["detector"] is None


class TestSeeding:
    """Verify seed data loads from integration/presets/."""

    def test_seeded_scan_presets(self, seeded_client):
        r = seeded_client.get("/api/v1/scan-presets")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) == 17
        r = seeded_client.get("/api/v1/scan-presets/Fe_L")
        assert r.status_code == 200
        assert r.json()["start"] == 698
        assert r.json()["scan_count"] == 8

    def test_seeded_detector_presets(self, seeded_client):
        r = seeded_client.get("/api/v1/detector-presets")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) == 17
        r = seeded_client.get("/api/v1/detector-presets/Cu_L")
        assert r.status_code == 200
        assert r.json()["samplegain"] == "2"
        assert r.json()["vortex_low"] == 820

    def test_seeded_full_preset(self, seeded_client):
        """Full view should return all three sub-objects for a shared edge."""
        r = seeded_client.get("/api/v1/edges/Fe_L/full")
        assert r.status_code == 200
        data = r.json()
        assert data["scan"] is not None
        assert data["detector"] is not None
        assert data["scan"]["scan_count"] == 8
        assert data["detector"]["samplegain"] == "5"
