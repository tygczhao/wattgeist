"""Kiro Crew review of a meter file's import settings (the `format-reviewer` agent).

Only the first 25 lines and the column names are sent, never the whole file: a preview is enough to judge the format and
keeps a household's year of usage private. The agent's instructions live in
crew-app/wattgeist-night-watch/agents/format-reviewer.json; it has no tools and must reply with one JSON object that
matches the schema sent with each request. The reply is validated against ParseConfig here, then the pipeline runs the
deterministic parser and scores it, discarding it unless it qualifies. The agent therefore does not need to be trusted,
only to offer a candidate worth trying.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ConfigDict

from ..ingest.config import ParseConfig
from .crew import FORMAT_REVIEW_AGENT, run_agent

log = logging.getLogger(__name__)

# The import is a synchronous request with the user waiting; on timeout the pipeline keeps the heuristic result
REVIEW_TIMEOUT_S = 120.0


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: ParseConfig
    notes: list[str]


def _extract_json(text: str) -> dict:
    """Extract the JSON object from the agent's reply.

    A Crew agent's output is constrained only by its prompt, not by API-enforced structured outputs, so a model may
    still wrap the object in a ``` fence or add a sentence around it. Parse from the first "{" to the last "}".
    Parse or validation errors are raised: the pipeline catches them and keeps the heuristic result (req. 3.4).
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("format reviewer returned no JSON object")
    return json.loads(text[start : end + 1])


class CrewFormatAssistant:
    """Implements the ingest.pipeline.FormatAssistant protocol."""

    def propose(
        self, preview: list[str], columns: list[str], current: ParseConfig, problems: list[str]
    ) -> tuple[ParseConfig, list[str]]:
        payload = {
            "file_preview": preview,
            "columns": columns,
            "current_guess": current.model_dump(),
            "problems": problems,
            # Sent with each request rather than written into the agent prompt, so it follows every ParseConfig change
            "reply_schema": _Proposal.model_json_schema(),
        }
        reply = run_agent(FORMAT_REVIEW_AGENT, json.dumps(payload, ensure_ascii=False), REVIEW_TIMEOUT_S)
        proposal = _Proposal.model_validate(_extract_json(reply))
        # The file type comes from magic bytes and the agent may not change it; doing so would only make the parser read the file the wrong way
        cfg = proposal.config.model_copy(update={"file_kind": current.file_kind})
        return cfg, [n for n in proposal.notes if n.strip()][:6]
