"""Notification response models must emit UTC (Z), not naive DB wall-clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.schemas.schemas import (
    AppNotificationRead,
    InventoryInstallerNoticeRead,
    InventoryReservationExpiryNoticeRead,
    InventoryReturnNoticeRead,
    InventoryShortageNoticeRead,
)
from app.utils.datetimes import to_api_utc_iso


def _client_for(model, factory):
    app = FastAPI()

    @app.get("/item", response_model=model)
    def item():
        return factory()

    return TestClient(app)


def test_all_notice_read_models_emit_utc_z_for_naive_db_wall_clock():
    naive = datetime(2026, 10, 10, 1, 57, 9)
    expected = to_api_utc_iso(naive)
    assert expected and expected.endswith("Z")

    cases = [
        (
            AppNotificationRead,
            lambda: AppNotificationRead(
                id=1,
                user_id=1,
                event_type="project_approved",
                title="t",
                message="m",
                href="/",
                priority="medium",
                created_at=naive,
            ),
        ),
        (
            InventoryInstallerNoticeRead,
            lambda: InventoryInstallerNoticeRead(
                id=1,
                user_id=1,
                notice_type="issued",
                created_at=naive,
            ),
        ),
        (
            InventoryReturnNoticeRead,
            lambda: InventoryReturnNoticeRead(
                id=1,
                issuance_id=1,
                returned_by_user_id=1,
                created_at=naive,
            ),
        ),
        (
            InventoryShortageNoticeRead,
            lambda: InventoryShortageNoticeRead(
                id=1,
                user_id=1,
                shortage_id=1,
                notice_type="shortage_created",
                qty=1,
                created_at=naive,
            ),
        ),
        (
            InventoryReservationExpiryNoticeRead,
            lambda: InventoryReservationExpiryNoticeRead(
                id=1,
                user_id=1,
                reservation_id=1,
                notice_type="reservation_idle_reminder",
                created_at=naive,
            ),
        ),
    ]

    for model, factory in cases:
        body = _client_for(model, factory).get("/item").json()
        assert body["created_at"] == expected, model.__name__


def test_aware_offset_timestamps_normalize_to_utc_z():
    aware = datetime(2026, 10, 9, 13, 33, 54, tzinfo=timezone(timedelta(hours=-7)))
    expected = to_api_utc_iso(aware)
    assert expected == "2026-10-09T20:33:54Z"

    body = (
        _client_for(
            InventoryShortageNoticeRead,
            lambda: InventoryShortageNoticeRead(
                id=1,
                user_id=1,
                shortage_id=1,
                notice_type="shortage_created",
                qty=1,
                created_at=aware,
            ),
        )
        .get("/item")
        .json()
    )
    assert body["created_at"] == expected
