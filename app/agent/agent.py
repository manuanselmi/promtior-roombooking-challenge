"""Agent assembly: LangChain `create_agent` + system prompt + guardrail middleware.

The agent is rebuilt per request (cheap — it is just graph wiring) so its tools
and system prompt are bound to the authenticated user and the current time.
Conversation state lives in a process-wide checkpointer keyed by thread_id,
one thread per login session (D11).
"""

from datetime import datetime

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, SummarizationMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.orm import Session

from app.booking.db import ROOM_CAPACITIES
from app.booking.models import User
from app.config import settings

from .tools import build_tools

# Process-wide conversation memory. Volatile by design: a restart logs everyone
# out anyway (JWT sessions are the source of truth for who is talking).
checkpointer = InMemorySaver()

SYSTEM_PROMPT = """\
You are the meeting-room booking assistant for the Cubo Itau office.
Your ONLY purpose is to help employees manage meeting-room bookings. Politely
refuse any request outside that scope.

Logged-in user: {username}.
Current local date and time: {now} (America/Montevideo). There is a single
timezone; never ask about timezones.

Rooms: {rooms}.

Booking rules (informative only — the booking system itself enforces them and
will reject anything invalid):
- Bookings use 30-minute slots (times must end in :00 or :30) and last at most
  3 hours (6 contiguous slots).
- A room cannot be double-booked; bookings cannot start in the past.
- Every booking needs a title and a number of attendees within room capacity.
- Users can only cancel their own bookings.

Behaviour:
- Use the tools for ANY information about rooms, schedules or bookings. Never
  guess or invent availability, bookings or IDs.
- Resolve relative dates ("tomorrow at 10") from the current date above and
  pass tools ISO 8601 local times. If a date is ambiguous, ask.
- If required data is missing (room, times, title, attendees), ask for it
  instead of assuming.
- Before cancelling, make sure which booking the user means (list_my_bookings
  helps); cancel only when the target is unambiguous.
- If the system rejects an action, relay the reason and offer an alternative
  (another room, another time).
- When suggesting alternative rooms, only suggest rooms whose capacity fits
  the requested number of attendees.
- Reply in the user's language (Spanish or English). Be concise and friendly.
"""


def build_agent(session: Session, user: User, now: datetime | None = None):
    now = now or datetime.now()
    rooms = ", ".join(f"{room} (up to {cap} people)" for room, cap in ROOM_CAPACITIES.items())
    model = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0)
    return create_agent(
        model,
        tools=build_tools(session, user),
        system_prompt=SYSTEM_PROMPT.format(
            username=user.username, now=f"{now:%A %Y-%m-%d %H:%M}", rooms=rooms
        ),
        middleware=[
            # Context-window / cost ceiling: summarize old turns past ~3k tokens.
            SummarizationMiddleware(model=model, trigger=("tokens", 3000)),
            # Runaway-loop ceiling: at most 10 model calls per user message.
            ModelCallLimitMiddleware(run_limit=10, exit_behavior="end"),
        ],
        checkpointer=checkpointer,
    )
