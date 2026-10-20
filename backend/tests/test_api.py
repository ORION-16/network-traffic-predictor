"""Tests for REST API endpoints using the FastAPI test client."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestCaptureEndpoints:
    def test_status_idle(self, client):
        resp = client.get("/api/capture/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_capturing" in data

    def test_stop_when_idle(self, client):
        resp = client.post("/api/capture/stop")
        assert resp.status_code == 409

    def test_export_csv_empty(self, client):
        resp = client.get("/api/capture/export/csv")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        # Should at least have the header row
        assert "timestamp" in resp.text
