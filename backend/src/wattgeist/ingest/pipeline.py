"""Import pipeline: heuristic inference -> deterministic parse -> AI review when needed -> keep the best-scoring result.

AI is only consulted when the heuristic parse fails, scores below AI_REVIEW_BELOW, or reports an ambiguity.
The AI config goes through parse_with_config and scoring like any other and is only adopted under the rules below,
so without AI (no key, timeout, invalid JSON) the import still completes, just without the second opinion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from .config import ParseConfig
from .infer import Inference, infer_config
from .parse import ParseResult, parse_with_config
from .table import ImportError_, detect_file_kind, raw_preview

log = logging.getLogger(__name__)

AI_REVIEW_BELOW = 90.0


class FormatAssistant(Protocol):
    """An assistant that proposes import settings from a file preview (the Kiro Crew agent implementation is llm/parse_assist.py)."""

    def propose(
        self, preview: list[str], columns: list[str], current: ParseConfig, problems: list[str]
    ) -> tuple[ParseConfig, list[str]]: ...


@dataclass
class ImportOutcome:
    result: ParseResult | None
    inference: Inference | None
    source: str  # heuristic | ai | user
    preview: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ai_notes: list[str] = field(default_factory=list)
    ai_used: bool = False
    error: str | None = None


def _try_parse(data: bytes, cfg: ParseConfig, tz: str | None, label: str) -> tuple[ParseResult | None, str | None]:
    """Turn every parse failure into a displayable error: uploads are endlessly varied and no exception should become a 500."""
    try:
        return parse_with_config(data, cfg, analysis_timezone=tz, label=label), None
    except ImportError_ as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001  third-party parsers (pandas, openpyxl) raise exception types that cannot be enumerated
        log.info("parse failed with %s: %s", type(exc).__name__, exc)
        return None, f"Could not read the file with these settings ({type(exc).__name__}: {exc})"


def import_meter_file(
    data: bytes,
    filename: str | None,
    timezone: str,
    *,
    analysis_timezone: str | None = None,
    config_override: ParseConfig | None = None,
    assistant: FormatAssistant | None = None,
    label: str = "",
) -> ImportOutcome:
    """Import one meter file. timezone is the default for naive timestamps; analysis_timezone defaults to the same."""
    tz = analysis_timezone or timezone
    if not data.strip():
        return ImportOutcome(result=None, inference=None, source="heuristic", error="The file is empty.")
    try:
        kind = detect_file_kind(data, filename)
        preview = raw_preview(data, kind)
    except ImportError_ as exc:
        return ImportOutcome(result=None, inference=None, source="heuristic", error=str(exc))
    except Exception as exc:  # noqa: BLE001  corrupt xlsx (not really a zip) and similar
        return ImportOutcome(result=None, inference=None, source="heuristic", error=f"Could not open the file: {exc}")

    if config_override is not None:
        result, err = _try_parse(data, config_override, tz, label)
        return ImportOutcome(result=result, inference=None, source="user", preview=preview, error=err)

    try:
        inference = infer_config(data, filename, timezone)
    except ImportError_ as exc:
        return ImportOutcome(result=None, inference=None, source="heuristic", preview=preview, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.info("inference failed: %s", exc)
        return ImportOutcome(
            result=None, inference=None, source="heuristic", preview=preview, error=f"Could not read the file: {exc}"
        )

    best, err = _try_parse(data, inference.config, tz, label)
    outcome = ImportOutcome(
        result=best, inference=inference, source="heuristic", preview=preview, notes=list(inference.notes), error=err
    )
    needs_review = best is None or best.report.score < AI_REVIEW_BELOW or bool(inference.ambiguities)
    if assistant is None or not needs_review or kind == "greenbutton_xml":
        return outcome

    problems = list(inference.ambiguities)
    if err:
        problems.append(f"Parsing failed: {err}")
    elif best is not None:
        problems.append(f"Quality score {best.report.score}/100.")
        problems.extend(best.report.warnings)
    try:
        ai_cfg, ai_notes = assistant.propose(preview, inference.columns, inference.config, problems)
    except Exception as exc:  # noqa: BLE001  AI failures cannot be enumerated (network, rate limit, refusal, invalid output); log and keep the heuristic result
        log.warning("format assistant failed: %s", exc)
        return outcome
    outcome.ai_used = True
    ai_result, ai_err = _try_parse(data, ai_cfg, tz, label)
    # Adoption rule: adopt the AI config when it scores higher, and also on an equal score when this review was triggered by an ambiguity.
    # Why: the score only measures internal consistency (regular timestamps, coverage, plausible power) and cannot tell W from Wh or interval start from end,
    # so both readings often score 100. The heuristic is guessing in exactly those places (hence the ambiguity), while the AI has read the notes above the header, so it wins ties.
    tie_break = best is not None and ai_result is not None and bool(inference.ambiguities) \
        and ai_result.report.score >= best.report.score
    if ai_result is not None and (best is None or ai_result.report.score > best.report.score or tie_break):
        outcome.result = ai_result
        outcome.source = "ai"
        outcome.error = None
        outcome.ai_notes = ai_notes
    elif ai_err:
        outcome.ai_notes = [f"The AI suggestion could not be parsed: {ai_err}"]
    else:
        outcome.ai_notes = ["The AI review agreed with (or did not improve on) the automatic reading."]
    return outcome
