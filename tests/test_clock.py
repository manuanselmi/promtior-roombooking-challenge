"""Tests for app.clock: the office wall clock must be Montevideo-local, not the
process/container timezone (which is UTC in production)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import clock
from app.booking import service
from app.booking.service import BookingError


def test_now_local_is_naive_montevideo_walltime():
    n = clock.now_local()
    assert n.tzinfo is None
    expected = datetime.now(ZoneInfo("America/Montevideo")).replace(tzinfo=None)
    assert abs((n - expected).total_seconds()) < 5


def test_now_local_is_not_the_utc_clock():
    # Uruguay is UTC-3 year-round (no DST since 2015); now_local must differ from
    # the naive UTC clock by ~3 hours, i.e. it is not the container's UTC time.
    utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = utc_naive - clock.now_local()
    assert abs(delta - timedelta(hours=3)).total_seconds() < 5


def test_create_booking_default_now_uses_office_clock(session, user1, monkeypatch):
    # Freeze the office clock; the default-now path must judge "past" against it.
    frozen = datetime(2030, 6, 15, 12, 0)
    monkeypatch.setattr(service, "now_local", lambda: frozen)

    future = service.create_booking(
        session,
        user=user1,
        room_id="A",
        start=datetime(2030, 6, 15, 12, 30),
        end=datetime(2030, 6, 15, 13, 0),
        title="Future meeting",
        attendees=1,
    )
    assert future.id is not None

    with pytest.raises(BookingError, match="past"):
        service.create_booking(
            session,
            user=user1,
            room_id="B",
            start=datetime(2030, 6, 15, 11, 30),
            end=datetime(2030, 6, 15, 12, 0),
            title="Past meeting",
            attendees=1,
        )


def test_explicit_now_still_overrides_office_clock(session, user1):
    # The injectable `now` parameter must keep winning over the office-clock default.
    booking = service.create_booking(
        session,
        user=user1,
        room_id="A",
        start=datetime(2030, 6, 15, 9, 0),
        end=datetime(2030, 6, 15, 9, 30),
        title="Explicit now",
        attendees=1,
        now=datetime(2030, 6, 15, 8, 0),
    )
    assert booking.id is not None
