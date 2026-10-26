"""API validation and dashboard payload shape."""

from fastapi.testclient import TestClient

from app.main import app
from monitoring.service import freshness_for


def test_freshness_states():
    assert freshness_for(None, 1, 100, "running") == "no_samples"
    assert freshness_for({"sampled_at": 100, "quality": "baseline"}, 1, 101, "running") == "baseline"
    assert freshness_for({"sampled_at": 0, "quality": "ok"}, 1, 100, "running") == "stale"
    assert freshness_for({"sampled_at": 99.5, "quality": "ok"}, 1, 100, "running") == "fresh"
    assert freshness_for({"sampled_at": 99.5, "quality": "ok"}, 1, 100, "interface_unavailable") == "stale"


def test_dashboard_contract_and_capacity_configuration():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["demo_mode"] is False

        interfaces = client.get("/api/monitoring/interfaces")
        assert interfaces.status_code == 200
        body = interfaces.json()
        assert body["interfaces"]
        assert "address" not in body["interfaces"][0]
        assert "mac" not in body["interfaces"][0]
        assert body["scope_note"]

        dashboard = client.get("/api/monitoring/dashboard")
        assert dashboard.status_code == 200
        payload = dashboard.json()
        for key in (
            "current",
            "history",
            "capacity",
            "forecast",
            "evaluation",
            "assessment",
            "collection",
            "interface",
            "units",
            "scope_note",
        ):
            assert key in payload
        assert payload["units"]["formula"] == "Mbps = byte_delta * 8 / elapsed_seconds / 1000000"
        assert payload["capacity"]["source"] == "unknown"
        assert payload["capacity"]["capacity_mbps"] is None
        assert payload["scope"] == "local_machine_interface"
        if payload["current"] is not None:
            assert payload["current"]["source"] == "psutil.net_io_counters"
            assert payload["current"]["quality"] in {"baseline", "ok", "gap", "counter_reset", "unsupported", "interface_changed"}

        rejected = client.put("/api/capacity", json={"capacity_mbps": 0, "direction": "per_direction"})
        assert rejected.status_code == 422
        bad_alpha = client.get("/api/forecast?alpha=0")
        assert bad_alpha.status_code == 422
        bad_iface = client.put("/api/monitoring/interface", json={"name": "not-a-real-interface"})
        assert bad_iface.status_code == 400

        saved = client.put(
            "/api/capacity",
            json={
                "capacity_mbps": 100,
                "direction": "per_direction",
                "warning_utilization_pct": 70,
                "high_utilization_pct": 85,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["capacity_source"] == "user"
        assert saved.json()["capacity_mbps"] == 100

        thresholds = client.put(
            "/api/thresholds",
            json={"latency_congestion_ms": 150, "loss_congestion_pct": 5},
        )
        assert thresholds.status_code == 200
        assert thresholds.json()["latency_congestion_ms"] == 150

        cleared = client.delete("/api/capacity")
        assert cleared.status_code == 200
        assert cleared.json()["capacity_mbps"] is None
        assert cleared.json()["capacity_source"] == "unknown"

        forecast = client.get("/api/forecast?method=moving_average&window=12&horizon_seconds=60")
        assert forecast.status_code == 200
        forecast_body = forecast.json()
        assert forecast_body["method"] == "moving_average"
        assert "accuracy" not in forecast_body
        assert forecast_body["status"] in {"ok", "insufficient_data"}
