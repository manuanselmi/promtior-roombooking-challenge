"""Tests for the LangChain tool layer — tools invoked directly, no LLM.

Verifies the two properties the agent design relies on (D11):
1. Tools are hard-bound to the logged-in user; identity is not a parameter.
2. Rule violations come back as strings, never exceptions, so the agent can
   only relay them.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from langchain_core.tools import BaseTool

from app.agent.tools import build_tools


def get(tools: list[BaseTool], name: str) -> BaseTool:
    return next(t for t in tools if t.name == name)


BOOKING = {
    "room": "B",
    "start": "2030-06-15T10:00:00",
    "end": "2030-06-15T11:00:00",
    "title": "Team sync",
    "attendees": 3,
}


@pytest.fixture()
def tools_u1(session_factory, user1):
    return build_tools(session_factory, user1)


@pytest.fixture()
def tools_u2(session_factory, user2):
    return build_tools(session_factory, user2)


class TestCreateBookingTool:
    def test_success_returns_confirmation(self, tools_u1):
        result = get(tools_u1, "create_booking").invoke(BOOKING)
        assert result.startswith("Booking confirmed.")
        assert "room B" in result

    def test_violation_returned_not_raised(self, tools_u1, tools_u2):
        get(tools_u1, "create_booking").invoke(BOOKING)
        result = get(tools_u2, "create_booking").invoke(BOOKING)
        assert result.startswith("BOOKING REJECTED:")
        assert "already booked" in result

    def test_iso_strings_are_parsed(self, tools_u1):
        result = get(tools_u1, "create_booking").invoke({**BOOKING, "start": "2030-06-15T10:30"})
        assert "10:30" in result


class TestIdentityBinding:
    def test_booking_belongs_to_bound_user(self, tools_u1, session, user1):
        get(tools_u1, "create_booking").invoke(BOOKING)
        assert "Team sync" in get(tools_u1, "list_my_bookings").invoke({})

    def test_other_user_sees_no_foreign_bookings(self, tools_u1, tools_u2, user2):
        get(tools_u1, "create_booking").invoke(BOOKING)
        assert "no upcoming bookings" in get(tools_u2, "list_my_bookings").invoke({})

    def test_cannot_cancel_foreign_booking(self, tools_u1, tools_u2):
        confirmation = get(tools_u1, "create_booking").invoke(BOOKING)
        booking_id = int(confirmation.split("#")[1].split(":")[0])
        result = get(tools_u2, "cancel_booking").invoke({"booking_id": booking_id})
        assert result.startswith("CANCELLATION REJECTED:")

    def test_owner_can_cancel(self, tools_u1):
        confirmation = get(tools_u1, "create_booking").invoke(BOOKING)
        booking_id = int(confirmation.split("#")[1].split(":")[0])
        result = get(tools_u1, "cancel_booking").invoke({"booking_id": booking_id})
        assert result.startswith("Cancelled.")


class TestQueryTools:
    RANGE = {"start": "2030-06-15T10:00:00", "end": "2030-06-15T11:00:00"}

    def test_available_rooms_lists_capacities(self, tools_u1):
        result = get(tools_u1, "list_available_rooms").invoke(self.RANGE)
        assert "A (up to 2 people)" in result
        assert "E (up to 10 people)" in result

    def test_available_rooms_excludes_booked(self, tools_u1):
        get(tools_u1, "create_booking").invoke(BOOKING)
        result = get(tools_u1, "list_available_rooms").invoke(self.RANGE)
        assert "B (" not in result

    def test_schedule_shows_occupied_and_free(self, tools_u1):
        get(tools_u1, "create_booking").invoke(BOOKING)
        result = get(tools_u1, "get_room_schedule").invoke(
            {"room": "b", "start": "2030-06-15T09:00:00", "end": "2030-06-15T12:00:00"}
        )
        assert "Team sync" in result
        assert "09:00 to 10:00" in result
        assert "11:00 to 12:00" in result

    def test_invalid_range_reported(self, tools_u1):
        result = get(tools_u1, "list_available_rooms").invoke(
            {"start": "2030-06-15T11:00:00", "end": "2030-06-15T10:00:00"}
        )
        assert result.startswith("INVALID RANGE:")


class TestTimezoneAwareInputs:
    """The LLM sometimes appends 'Z' or an offset to ISO datetimes; pydantic then
    parses them as timezone-aware. That must come back as a rejection string the
    agent can relay — never as an unhandled TypeError."""

    def test_create_with_utc_suffix_rejected(self, tools_u1):
        result = get(tools_u1, "create_booking").invoke(
            {**BOOKING, "start": "2030-06-15T10:00:00Z", "end": "2030-06-15T11:00:00Z"}
        )
        assert result.startswith("BOOKING REJECTED:")
        assert "offset" in result

    def test_schedule_with_offset_rejected(self, tools_u1):
        result = get(tools_u1, "get_room_schedule").invoke(
            {"room": "B", "start": "2030-06-15T10:00:00-03:00", "end": "2030-06-15T12:00:00-03:00"}
        )
        assert result.startswith("INVALID REQUEST:")
        assert "offset" in result

    def test_available_rooms_with_offset_rejected(self, tools_u1):
        result = get(tools_u1, "list_available_rooms").invoke(
            {"start": "2030-06-15T10:00:00+00:00", "end": "2030-06-15T11:00:00+00:00"}
        )
        assert result.startswith("INVALID RANGE:")
        assert "offset" in result


class TestParallelToolCalls:
    """LangChain's ToolNode runs the tool calls of a single model turn on
    separate threads. Each tool invocation opens its own session, so mixed
    reads and writes must stay correct under that concurrency (D14)."""

    def test_concurrent_creates_and_reads_are_isolated(self, tools_u1):
        create = get(tools_u1, "create_booking")
        schedule = get(tools_u1, "get_room_schedule")
        for day in range(1, 11):
            when = {
                "start": f"2030-06-{day:02d}T10:00:00",
                "end": f"2030-06-{day:02d}T11:00:00",
            }
            calls = [
                (create, {**BOOKING, **when, "room": "B"}),
                (create, {**BOOKING, **when, "room": "C"}),
                (schedule, {"room": "A", **when}),
            ]
            with ThreadPoolExecutor(max_workers=len(calls)) as pool:
                results = list(pool.map(lambda c: c[0].invoke(c[1]), calls))
            assert results[0].startswith("Booking confirmed."), results[0]
            assert results[1].startswith("Booking confirmed."), results[1]
            assert results[2].startswith("Schedule for room A"), results[2]
