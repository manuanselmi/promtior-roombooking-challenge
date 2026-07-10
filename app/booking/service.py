"""Booking business rules — the single source of truth.

Every rule from the challenge (30-minute slots, max 3 hours, no overlaps, room
capacity, cancel-own-only) is enforced here, never in the agent or its prompt.
The LLM can only call these functions; if a call violates a rule it gets a
`BookingError` back and can do nothing but report it.

A booking is modelled as one contiguous [start, end) range aligned to 30-minute
boundaries, which makes non-contiguous slot combinations unrepresentable.

All datetimes are naive local time (America/Montevideo).
"""

import threading
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Booking, Room, User

SLOT_MINUTES = 30
MAX_DURATION = timedelta(hours=3)

# FastAPI runs sync endpoints in a threadpool, so two requests can interleave
# between the overlap check and the insert. The app deploys as a single process
# (one container, D5), so a process-wide lock closes that window; a multi-process
# deployment would need a database-level guarantee instead (e.g. a Postgres
# exclusion constraint on (room_id, tsrange(start, end))).
_BOOKING_WRITE_LOCK = threading.Lock()


class BookingError(Exception):
    """Business-rule violation. The message is safe to show to the end user."""


def _get_room(session: Session, room_id: str) -> Room:
    room = session.get(Room, room_id.strip().upper())
    if room is None:
        raise BookingError(f"Room '{room_id}' does not exist. Available rooms are A to E.")
    return room


def _validate_slot_alignment(start: datetime, end: datetime) -> None:
    for name, dt in (("start", start), ("end", end)):
        if dt.minute % SLOT_MINUTES or dt.second or dt.microsecond:
            raise BookingError(
                f"The {name} time must align to 30-minute slots (e.g. 10:00 or 10:30), "
                f"got {dt:%H:%M}."
            )
    if end <= start:
        raise BookingError("The end time must be after the start time.")
    if end - start > MAX_DURATION:
        raise BookingError("A booking can last at most 3 hours (6 contiguous 30-minute slots).")


def _validate_query_range(start: datetime, end: datetime) -> None:
    if end <= start:
        raise BookingError("The end time must be after the start time.")


def _overlapping(session: Session, room_id: str, start: datetime, end: datetime) -> list[Booking]:
    stmt = (
        select(Booking)
        .where(Booking.room_id == room_id, Booking.start < end, Booking.end > start)
        .order_by(Booking.start)
    )
    return list(session.scalars(stmt))


def create_booking(
    session: Session,
    *,
    user: User,
    room_id: str,
    start: datetime,
    end: datetime,
    title: str,
    attendees: int,
    now: datetime | None = None,
) -> Booking:
    """Create a booking for `user`, enforcing every business rule."""
    room = _get_room(session, room_id)
    _validate_slot_alignment(start, end)

    if not title or not title.strip():
        raise BookingError("Every booking requires a title (e.g. 'Interview with John Doe').")
    if attendees < 1:
        raise BookingError("A booking needs at least 1 attendee.")
    if attendees > room.capacity:
        raise BookingError(
            f"Room {room.id} holds at most {room.capacity} people, got {attendees}. "
            f"Try a bigger room."
        )
    if start < (now or datetime.now()):
        raise BookingError("Bookings cannot start in the past.")

    with _BOOKING_WRITE_LOCK:
        conflicts = _overlapping(session, room.id, start, end)
        if conflicts:
            taken = ", ".join(f"{b.start:%Y-%m-%d %H:%M}–{b.end:%H:%M}" for b in conflicts)
            raise BookingError(f"Room {room.id} is already booked in that range ({taken}).")

        booking = Booking(
            room_id=room.id,
            user_id=user.id,
            title=title.strip(),
            attendees=attendees,
            start=start,
            end=end,
        )
        session.add(booking)
        session.commit()
    return booking


def list_available_rooms(session: Session, start: datetime, end: datetime) -> list[Room]:
    """Rooms with no booking overlapping [start, end)."""
    _validate_query_range(start, end)
    busy = select(Booking.room_id).where(Booking.start < end, Booking.end > start)
    stmt = select(Room).where(Room.id.not_in(busy)).order_by(Room.id)
    return list(session.scalars(stmt))


def get_room_schedule(
    session: Session, room_id: str, start: datetime, end: datetime
) -> tuple[list[Booking], list[tuple[datetime, datetime]]]:
    """Return (occupied bookings, free gaps) for a room within [start, end)."""
    room = _get_room(session, room_id)
    _validate_query_range(start, end)

    bookings = _overlapping(session, room.id, start, end)
    free: list[tuple[datetime, datetime]] = []
    cursor = start
    for b in bookings:
        if b.start > cursor:
            free.append((cursor, b.start))
        cursor = max(cursor, b.end)
    if cursor < end:
        free.append((cursor, end))
    return bookings, free


def list_user_bookings(
    session: Session, user: User, *, include_past: bool = False, now: datetime | None = None
) -> list[Booking]:
    stmt = select(Booking).where(Booking.user_id == user.id).order_by(Booking.start)
    if not include_past:
        stmt = stmt.where(Booking.end >= (now or datetime.now()))
    return list(session.scalars(stmt))


def cancel_booking(session: Session, *, user: User, booking_id: int) -> Booking:
    """Cancel a booking; only the user who created it may cancel it."""
    booking = session.get(Booking, booking_id)
    if booking is None:
        raise BookingError(f"Booking {booking_id} does not exist.")
    if booking.user_id != user.id:
        raise BookingError("You can only cancel your own bookings.")
    session.delete(booking)
    session.commit()
    return booking
