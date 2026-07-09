"""LangChain tools — thin wrappers around app.booking.service.

Tools are built per request, bound via closures to the DB session and the
authenticated user. The user's identity is deliberately NOT a tool parameter:
the LLM cannot spoof it, no matter what the conversation says (D11).

Tools return plain strings (what the model reads). Business-rule violations
are returned as "BOOKING REJECTED: ..." strings — never raised — so the agent
can only relay the reason; the rules themselves live in the service layer.
"""

from datetime import datetime

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from app.booking import service
from app.booking.models import Booking, User
from app.booking.service import BookingError


def _fmt(b: Booking) -> str:
    return (
        f"Booking #{b.id}: room {b.room_id}, {b.start:%A} {b.start:%Y-%m-%d} "
        f'{b.start:%H:%M}-{b.end:%H:%M}, "{b.title}", {b.attendees} attendee(s)'
    )


def build_tools(session: Session, user: User) -> list[BaseTool]:
    """Build the tool set bound to this request's DB session and logged-in user."""

    @tool
    def create_booking(
        room: str, start: datetime, end: datetime, title: str, attendees: int
    ) -> str:
        """Book a meeting room for the logged-in user.

        Args:
            room: Room letter, "A" to "E".
            start: Booking start, ISO 8601 local time, aligned to 30-minute slots.
            end: Booking end, ISO 8601 local time, aligned to 30-minute slots.
            title: Meeting title (required, e.g. "Interview with John Doe").
            attendees: Number of attendees; must not exceed the room's capacity.
        """
        try:
            booking = service.create_booking(
                session,
                user=user,
                room_id=room,
                start=start,
                end=end,
                title=title,
                attendees=attendees,
            )
        except BookingError as e:
            return f"BOOKING REJECTED: {e}"
        return f"Booking confirmed. {_fmt(booking)}"

    @tool
    def list_available_rooms(start: datetime, end: datetime) -> str:
        """List rooms that are completely free within a time range.

        Args:
            start: Range start, ISO 8601 local time.
            end: Range end, ISO 8601 local time.
        """
        try:
            rooms = service.list_available_rooms(session, start, end)
        except BookingError as e:
            return f"INVALID RANGE: {e}"
        if not rooms:
            return f"No rooms are available between {start:%Y-%m-%d %H:%M} and {end:%H:%M}."
        listed = ", ".join(f"{r.id} (up to {r.capacity} people)" for r in rooms)
        return f"Available between {start:%Y-%m-%d %H:%M} and {end:%H:%M}: {listed}."

    @tool
    def get_room_schedule(room: str, start: datetime, end: datetime) -> str:
        """Show a room's schedule (occupied bookings and free gaps) within a time range.

        Args:
            room: Room letter, "A" to "E".
            start: Range start, ISO 8601 local time.
            end: Range end, ISO 8601 local time.
        """
        try:
            bookings, free = service.get_room_schedule(session, room, start, end)
        except BookingError as e:
            return f"INVALID REQUEST: {e}"
        occupied = "\n".join(f"- {_fmt(b)}" for b in bookings) if bookings else "- none"
        gaps = (
            "\n".join(f"- {s:%Y-%m-%d %H:%M} to {e:%H:%M}" for s, e in free) if free else "- none"
        )
        return (
            f"Schedule for room {room.strip().upper()} "
            f"between {start:%Y-%m-%d %H:%M} and {end:%H:%M}:\n"
            f"Occupied:\n{occupied}\nFree:\n{gaps}"
        )

    @tool
    def list_my_bookings() -> str:
        """List the logged-in user's upcoming bookings, with their booking IDs."""
        bookings = service.list_user_bookings(session, user)
        if not bookings:
            return f"{user.username} has no upcoming bookings."
        return f"Upcoming bookings for {user.username}:\n" + "\n".join(
            f"- {_fmt(b)}" for b in bookings
        )

    @tool
    def cancel_booking(booking_id: int) -> str:
        """Cancel one of the logged-in user's bookings.

        Args:
            booking_id: ID of the booking to cancel (see list_my_bookings).
        """
        try:
            booking = service.cancel_booking(session, user=user, booking_id=booking_id)
        except BookingError as e:
            return f"CANCELLATION REJECTED: {e}"
        return f"Cancelled. {_fmt(booking)}"

    return [
        create_booking,
        list_available_rooms,
        get_room_schedule,
        list_my_bookings,
        cancel_booking,
    ]
