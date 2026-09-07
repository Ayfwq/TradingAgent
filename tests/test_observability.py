from __future__ import annotations

import re

from fastapi.testclient import TestClient

from web.app import app

client = TestClient(app)


def _metric_value(text: str, metric: str, **labels: str) -> float:
    label_pattern = ".*".join(
        rf'{re.escape(name)}="{re.escape(value)}"' for name, value in labels.items()
    )
    match = re.search(
        rf"^{re.escape(metric)}\{{[^}}]*{label_pattern}[^}}]*\}}\s+([0-9.eE+-]+)$",
        text,
        re.MULTILINE,
    )
    assert match is not None, f"missing {metric} with labels {labels}"
    return float(match.group(1))


def test_health_is_healthy() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status": "healthy"}


def test_metrics_is_prometheus_text() -> None:
    response = client.get("/metrics")
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=")
    assert "# HELP http_requests_total" in body
    assert "# TYPE http_request_duration_seconds histogram" in body
    assert "process_cpu_seconds_total" in body
    assert "process_resident_memory_bytes" in body


def test_business_request_increments_route_counter() -> None:
    assert client.get("/api/model-templates").status_code == 200
    before = client.get("/metrics").text
    before_value = _metric_value(
        before,
        "http_requests_total",
        handler="/api/model-templates",
        method="GET",
        status="200",
    )

    assert client.get("/api/model-templates").status_code == 200

    after = client.get("/metrics").text
    after_value = _metric_value(
        after,
        "http_requests_total",
        handler="/api/model-templates",
        method="GET",
        status="200",
    )
    assert after_value == before_value + 1
