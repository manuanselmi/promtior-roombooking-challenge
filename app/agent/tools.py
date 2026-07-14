"""LangChain tools — thin wrappers around app.booking.service.

Tools are built per request, bound via closures to the authenticated user.
The user's identity is deliberately NOT a tool parameter: the LLM cannot
spoof it, no matter what the conversation says (D11).

Each tool invocation opens its own short-lived DB session: LangChain's
ToolNode runs parallel tool calls from a single model turn on separate
threads, and a shared SQLAlchemy Session is not thread-safe (D14). For the
same reason the closures capture the user's id/username as plain values —
the ORM instance belongs to the request's session.

Tools return plain strings (what the model reads). Business-rule violations
are returned as "BOOKING REJECTED: ..." strings — never raised — so the agent
can only relay the reason; the rules themselves live in the service layer.
"""

from collections.abc import Callable
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


def build_tools(session_factory: Callable[[], Session], user: User) -> list[BaseTool]:
    """Build the tool set bound to the logged-in user; one DB session per call."""
    user_id, username = user.id, user.username

    @tool
    def create_booking(
        room: str, start: datetime, end: datetime, title: str, attendees: int
    ) -> str:
        """Book a meeting room for the logged-in user.

        Call this ONLY when the user has explicitly provided every argument
        below. Never invent or default a value just to complete the call: if
        the title or the end time is missing, ask the user first. There is no
        default duration and no default title.

        Args:
            room: Room letter, "A" to "E".
            start: Booking start, ISO 8601 local time without timezone offset
                or 'Z' (e.g. 2030-06-15T10:00), aligned to 30-minute slots.
            end: Booking end, same format as start, aligned to 30-minute slots.
                There is NO default duration: if the user gave only a start
                time, do NOT call this tool — ask how long the meeting lasts
                (or until when) and wait for the answer.
            title: Meeting title exactly as the user states it; never make one
                up (not from the room, the time, or anything else).
            attendees: Number of attendees; must not exceed the room's capacity.
        """
        try:
            with session_factory() as session:
                booking = service.create_booking(
                    session,
                    user=session.get(User, user_id),
                    room_id=room,
                    start=start,
                    end=end,
                    title=title,
                    attendees=attendees,
                )
                return f"Booking confirmed. {_fmt(booking)}"
        except BookingError as e:
            return f"BOOKING REJECTED: {e}"

    @tool
    def list_available_rooms(start: datetime, end: datetime) -> str:
        """List rooms that are completely free within a time range.

        Args:
            start: Range start, ISO 8601 local time without timezone offset or 'Z'.
            end: Range end, same format as start.
        """
        try:
            with session_factory() as session:
                rooms = service.list_available_rooms(session, start, end)
                listed = ", ".join(f"{r.id} (up to {r.capacity} people)" for r in rooms)
        except BookingError as e:
            return f"INVALID RANGE: {e}"
        if not listed:
            return f"No rooms are available between {start:%Y-%m-%d %H:%M} and {end:%H:%M}."
        return f"Available between {start:%Y-%m-%d %H:%M} and {end:%H:%M}: {listed}."

    @tool
    def get_room_schedule(room: str, start: datetime, end: datetime) -> str:
        """Show a room's schedule (occupied bookings and free gaps) within a time range.

        Args:
            room: Room letter, "A" to "E".
            start: Range start, ISO 8601 local time without timezone offset or 'Z'.
            end: Range end, same format as start.
        """
        try:
            with session_factory() as session:
                bookings, free = service.get_room_schedule(session, room, start, end)
                occupied = "\n".join(f"- {_fmt(b)}" for b in bookings) if bookings else "- none"
        except BookingError as e:
            return f"INVALID REQUEST: {e}"
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
        with session_factory() as session:
            bookings = service.list_user_bookings(session, session.get(User, user_id))
            if not bookings:
                return f"{username} has no upcoming bookings."
            return f"Upcoming bookings for {username}:\n" + "\n".join(
                f"- {_fmt(b)}" for b in bookings
            )

    @tool
    def cancel_booking(booking_id: int) -> str:
        """Cancel one of the logged-in user's bookings.

        Args:
            booking_id: ID of the booking to cancel (see list_my_bookings).
        """
        try:
            with session_factory() as session:
                booking = service.cancel_booking(
                    session, user=session.get(User, user_id), booking_id=booking_id
                )
                return f"Cancelled. {_fmt(booking)}"
        except BookingError as e:
            return f"CANCELLATION REJECTED: {e}"

    return [
        create_booking,
        list_available_rooms,
        get_room_schedule,
        list_my_bookings,
        cancel_booking,
    ]
