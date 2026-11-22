"""Kiro PreToolUse hook: stop the agent from hand-editing data files that scripts generate.

Kiro writes the tool-call context as JSON to STDIN (including tool_name and tool_input).
On a protected path it exits non-zero with the reason on STDERR, and Kiro blocks the write.
Protected files can only be regenerated with scripts/build_demo_data.py and scripts/fetch_octopus_tariffs.py.
"""

from __future__ import annotations

import json
import re
import sys

PROTECTED = re.compile(
    r"backend/src/wattgeist/data/(benchmark\.json|tariffs_uk\.json|demo/[^/]+\.(csv\.gz|json))$"
)


def _paths(value) -> list[str]:
    """Tool input shapes differ by tool, so collect every string field that looks like a path, recursively."""
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and k.lower() in {"path", "file_path", "filepath", "target", "filename"}:
                out.append(v)
            else:
                out.extend(_paths(v))
    elif isinstance(value, list):
        for v in value:
            out.extend(_paths(v))
    return out


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    hits = [p for p in _paths(event.get("tool_input", {})) if PROTECTED.search(p.replace("\\", "/"))]
    if hits:
        print(
            "Blocked: " + ", ".join(hits) + " is generated. Re-run scripts/build_demo_data.py or "
            "scripts/fetch_octopus_tariffs.py instead of editing it by hand.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
