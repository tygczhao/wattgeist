"""Start the WattGeist MCP server for Kiro Crew.

Crew resolves a bare `python3` with an app-relative .py launcher to absolute paths at registration, so this file is
the stable entry point. It runs `uv run wattgeist-mcp` against the bundled backend. uv is looked up on PATH and in
the usual install locations because a Crew service may run with a minimal PATH.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
# The data directory is shared with the WattGeist web backend (default ~/.wattgeist, as in service.data_dir()).
# Why: the web app's Séance and import review are this app's Kiro Crew agents, which read households through this
# MCP server. With an app-private data directory, homes uploaded in the browser would be invisible to the agents.
# An explicit WATTGEIST_DATA_DIR wins (the web backend passes its own when it runs kirocrew).
SHARED_DATA_DIR = Path.home() / ".wattgeist"


def find_uv() -> str:
    for candidate in (shutil.which("uv"), str(Path.home() / ".local/bin/uv"), str(Path.home() / ".cargo/bin/uv")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    sys.stderr.write("WattGeist Night Watch needs uv (https://docs.astral.sh/uv/) to start its MCP server.\n")
    sys.exit(1)


def main() -> None:
    env = dict(os.environ)
    env.setdefault("WATTGEIST_DATA_DIR", str(SHARED_DATA_DIR))
    env.setdefault("WATTGEIST_DISABLE_AI", "1")
    uv = find_uv()
    # exec keeps stdio attached directly to the MCP server, which speaks JSON-RPC on stdout
    os.execve(uv, [uv, "run", "--quiet", "--project", str(APP_ROOT / "backend"), "wattgeist-mcp"], env)


if __name__ == "__main__":
    main()
