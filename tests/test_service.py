"""Business-rule tests for app.booking.service — no LLM involved."""

from datetime import datetime

import pytest

from app.booking import service
from app.booking.service import BookingError


# Fixed dates far in the future so the "no bookings in the past" rule never trips.
def t(hour: int, minute: int = 0, day: int = 15) -> datetime:
    return datetime(2030, 6, day, hour, minute)


def make(session, user, **overrides):
    defaults = dict(user=user, room_id="B", start=t(10), end=t(11), title="Team sync", attendees=3)
    return service.create_booking(session, **{**defaults, **overrides})


class TestCreateBooking:
    def test_creates_and_persists(self, session, user1):
        booking = make(session, user1)
        assert booking.id is not None
        assert booking.room_id == "B"
        assert booking.user_id == user1.id
        assert booking.title == "Team sync"

    def test_room_id_is_normalized(self, session, user1):
        booking = make(session, user1, room_id=" b ")
        assert booking.room_id == "B"

    def test_unknown_room_rejected(self, session, user1):
        with pytest.raises(BookingError, match="does not exist"):
            make(session, user1, room_id="Z")

    def test_unaligned_start_rejected(self, session, user1):
        with pytest.raises(BookingError, match="align"):
            make(session, user1, start=t(10, 15), end=t(11, 15))

    def test_end_before_start_rejected(self, session, user1):
        with pytest.raises(BookingError, match="after the start"):
            make(session, user1, start=t(11), end=t(10))

    def test_zero_length_rejected(self, session, user1):
        with pytest.raises(BookingError, match="after the start"):
            make(session, user1, start=t(10), end=t(10))

    def test_over_three_hours_rejected(self, session, user1):
        with pytest.raises(BookingError, match="3 hours"):
            make(session, user1, start=t(10), end=t(13, 30))

    def test_exactly_three_hours_ok(self, session, user1):
        booking = make(session, user1, start=t(10), end=t(13))
        assert booking.id is not None

    def test_single_slot_ok(self, session, user1):
        booking = make(session, user1, start=t(10), end=t(10, 30))
        assert booking.id is not None

    def test_capacity_exceeded_rejected(self, session, user1):
        with pytest.raises(BookingError, match="at most 2"):
            make(session, user1, room_id="A", attendees=3)

    def test_attendees_at_capacity_ok(self, session, user1):
        booking = make(session, user1, room_id="A", attendees=2)
        assert booking.id is not None

    def test_zero_attendees_rejected(self, session, user1):
        with pytest.raises(BookingError, match="at least 1"):
            make(session, user1, attendees=0)

    def test_empty_title_rejected(self, session, user1):
        with pytest.raises(BookingError, match="title"):
            make(session, user1, title="   ")

    def test_past_booking_rejected(self, session, user1):
        with pytest.raises(BookingError, match="past"):
            make(session, user1, start=datetime(2020, 1, 1, 10), end=datetime(2020, 1, 1, 11))


class TestOverlaps:
    """The PDF's example: a 10:00–11:30 booking blocks anything starting before 11:30."""

    def test_pdf_example_earlier_start_conflicts(self, session, user1, user2):
        make(session, user1, start=t(10), end=t(11, 30))
        with pytest.raises(BookingError, match="already booked"):
            make(session, user2, start=t(11), end=t(12))

    def test_pdf_example_start_at_end_ok(self, session, user1, user2):
        make(session, user1, start=t(10), end=t(11, 30))
        booking = make(session, user2, start=t(11, 30), end=t(12, 30))
        assert booking.id is not None

    def test_partial_overlap_from_before_conflicts(self, session, user1, user2):
        make(session, user1, start=t(10), end=t(11, 30))
        with pytest.raises(BookingError, match="already booked"):
            make(session, user2, start=t(9, 30), end=t(10, 30))

    def test_contained_range_conflicts(self, session, user1, user2):
        make(session, user1, start=t(10), end=t(11, 30))
        with pytest.raises(BookingError, match="already booked"):
            make(session, user2, start=t(10, 30), end=t(11))

    def test_back_to_back_before_ok(self, session, user1, user2):
        make(session, user1, start=t(10), end=t(11, 30))
        booking = make(session, user2, start=t(9), end=t(10))
        assert booking.id is not None

    def test_same_range_other_room_ok(self, session, user1, user2):
        make(session, user1, room_id="B", start=t(10), end=t(11, 30))
        booking = make(session, user2, room_id="C", start=t(10), end=t(11, 30))
        assert booking.id is not None

    def test_same_user_cannot_double_book_room(self, session, user1):
        make(session, user1, start=t(10), end=t(11))
        with pytest.raises(BookingError, match="already booked"):
            make(session, user1, start=t(10), end=t(11))


class TestListAvailableRooms:
    def test_all_free_initially(self, session):
        rooms = service.list_available_rooms(session, t(10), t(11))
        assert [r.id for r in rooms] == ["A", "B", "C", "D", "E"]

    def test_booked_room_excluded(self, session, user1):
        make(session, user1, room_id="C", start=t(10), end=t(11))
        rooms = service.list_available_rooms(session, t(10, 30), t(11, 30))
        assert [r.id for r in rooms] == ["A", "B", "D", "E"]

    def test_adjacent_booking_does_not_exclude(self, session, user1):
        make(session, user1, room_id="C", start=t(10), end=t(11))
        rooms = service.list_available_rooms(session, t(11), t(12))
        assert "C" in [r.id for r in rooms]

    def test_invalid_range_rejected(self, session):
        with pytest.raises(BookingError, match="after the start"):
            service.list_available_rooms(session, t(11), t(10))


class TestRoomSchedule:
    def test_free_room_is_one_gap(self, session):
        bookings, free = service.get_room_schedule(session, "B", t(9), t(12))
        assert bookings == []
        assert free == [(t(9), t(12))]

    def test_occupied_and_free_gaps(self, session, user1):
        make(session, user1, room_id="B", start=t(10), end=t(11))
        bookings, free = service.get_room_schedule(session, "B", t(9), t(12))
        assert [(b.start, b.end) for b in bookings] == [(t(10), t(11))]
        assert free == [(t(9), t(10)), (t(11), t(12))]

    def test_fully_booked_no_gaps(self, session, user1):
        make(session, user1, room_id="B", start=t(9), end=t(12))
        bookings, free = service.get_room_schedule(session, "B", t(9), t(12))
        assert len(bookings) == 1
        assert free == []

    def test_booking_spilling_over_range_edges(self, session, user1):
        make(session, user1, room_id="B", start=t(9), end=t(10, 30))
        bookings, free = service.get_room_schedule(session, "B", t(10), t(12))
        assert len(bookings) == 1
        assert free == [(t(10, 30), t(12))]


class TestCancelBooking:
    def test_cancel_own(self, session, user1):
        booking = make(session, user1)
        service.cancel_booking(session, user=user1, booking_id=booking.id)
        assert service.list_user_bookings(session, user1, now=t(0, 0, day=1)) == []

    def test_cancel_frees_the_slot(self, session, user1, user2):
        booking = make(session, user1)
        service.cancel_booking(session, user=user1, booking_id=booking.id)
        rebooked = make(session, user2)
        assert rebooked.id is not None

    def test_cannot_cancel_others(self, session, user1, user2):
        booking = make(session, user1)
        with pytest.raises(BookingError, match="your own"):
            service.cancel_booking(session, user=user2, booking_id=booking.id)

    def test_cancel_nonexistent_rejected(self, session, user1):
        with pytest.raises(BookingError, match="does not exist"):
            service.cancel_booking(session, user=user1, booking_id=999)


class TestListUserBookings:
    def test_only_own_upcoming_sorted(self, session, user1, user2):
        make(session, user1, start=t(14), end=t(15))
        make(session, user1, start=t(10), end=t(11))
        make(session, user2, room_id="C", start=t(10), end=t(11))
        result = service.list_user_bookings(session, user1, now=t(0, 0, day=1))
        assert [b.start for b in result] == [t(10), t(14)]
        assert all(b.user_id == user1.id for b in result)
