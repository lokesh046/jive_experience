"""Liveness, readiness, metadata and the shared error envelope."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app import __version__


async def test_liveness_is_dependency_free(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


async def test_liveness_also_served_under_api_version(client: AsyncClient) -> None:
    response = await client.get("/api/v1/system/health")
    assert response.status_code == 200


async def test_every_response_carries_a_correlation_id(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers["X-Request-ID"]


async def test_supplied_correlation_id_is_echoed(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


async def test_security_headers_present(client: AsyncClient) -> None:
    headers = (await client.get("/health")).headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    # The staff scanner needs the device camera; nothing else is permitted.
    assert "camera=(self)" in headers["Permissions-Policy"]


async def test_hsts_not_sent_outside_production(client: AsyncClient) -> None:
    assert "Strict-Transport-Security" not in (await client.get("/health")).headers


@pytest.mark.parametrize(
    ("db_ok", "redis_ok", "expected_status", "expected_state"),
    [
        (True, True, 200, "ready"),
        (False, True, 503, "degraded"),
        (True, False, 503, "degraded"),
        (False, False, 503, "degraded"),
    ],
)
async def test_readiness_reflects_dependencies(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_ok: bool,
    redis_ok: bool,
    expected_status: int,
    expected_state: str,
) -> None:
    async def fake_db() -> bool:
        return db_ok

    async def fake_redis() -> bool:
        return redis_ok

    monkeypatch.setattr("app.router.v1.system.database_healthy", fake_db)
    monkeypatch.setattr("app.router.v1.system.redis_healthy", fake_redis)

    response = await client.get("/api/v1/system/health/ready")
    assert response.status_code == expected_status
    body = response.json()
    assert body["status"] == expected_state
    assert body["dependencies"] == {"database": db_ok, "redis": redis_ok}


async def test_service_info(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/system/info")).json()
    assert body["api_version"] == "v1"
    assert body["environment"] == "test"
    assert body["currency"] == "INR"
    assert body["default_timezone"] == "Asia/Kolkata"


async def test_unknown_route_uses_the_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "details" in error


async def test_openapi_is_served_outside_production(client: AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    assert "/api/v1/system/info" in schema["paths"]
    # Unversioned probe aliases are excluded from the published contract.
    assert "/health" not in schema["paths"]
