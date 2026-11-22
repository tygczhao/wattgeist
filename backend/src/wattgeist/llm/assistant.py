"""The Q&A assistant (the "séance"): the `seance` Kiro Crew agent, streamed to the frontend.

The agent (crew-app/wattgeist-night-watch/agents/seance.json) holds the medium's instructions and may call only the
read-only WattGeist MCP tools; Kiro Crew runs the tool loop. The browser keeps the history and sends it in full each
time; the server is stateless and replays it to the agent as a plain-text transcript, so earlier turns are only ever
appended to, never rewritten.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

from .. import service
from .crew import SEANCE_AGENT, CrewError, stream_agent

log = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20
# Wall-clock limit for one answer: kirocrew start-up, the MCP server's cold start (uv run) and every tool round.
# Kiro Crew's agent loop now bounds the tool rounds; this limit only stops a runaway agent from holding a request.
ANSWER_TIMEOUT_S = 240.0


def _message(h: service.Household, question: str, history: list[dict]) -> str:
    """Build the single message sent to the seance agent.

    Every `kirocrew chat -m` call is a new session with no memory, so the history the browser sends back is turned
    into a transcript placed before the question. The household id must be stated explicitly: the agent passes it to
    the MCP tools, and the MCP server holds the demo homes and every uploaded home. History and question are
    user-controlled text; the agent prompt says they are data, not instructions.
    """
    card = service.household_card(h)
    lines = [
        f"Household id: {h.id}",
        "Household summary: "
        + json.dumps({"household": card, "data_note": "Demo homes are real London households from 2011-2014."}),
    ]
    turns = []
    for turn in history[-MAX_HISTORY_TURNS:]:
        role, text = turn.get("role"), str(turn.get("content", ""))[:4000].strip()
        if role in ("user", "assistant") and text:
            turns.append(f"{'User' if role == 'user' else 'Medium'}: {text}")
    if turns:
        lines += ["", "Conversation so far:", *turns]
    lines += ["", f"New question: {question[:4000]}"]
    return "\n".join(lines)


def ask(h: service.Household, question: str, history: list[dict]) -> Iterator[dict]:
    """Yield events: {"type": "text", "delta"} / {"type": "done"} / {"type": "error", "message"}."""
    try:
        for delta in stream_agent(SEANCE_AGENT, _message(h, question, history), ANSWER_TIMEOUT_S):
            yield {"type": "text", "delta": delta}
    except CrewError as exc:
        # The cause goes to the log only; the user sees a short message with no local paths or traceback (req. 2.3)
        log.warning("seance agent failed: %s", exc)
        hint = " (sign in to Kiro in Kiro Crew)" if "not signed in" in str(exc) else ""
        yield {"type": "error", "message": f"The medium could not reach the other side{hint}."}
        return
    yield {"type": "done"}
