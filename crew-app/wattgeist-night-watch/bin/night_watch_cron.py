"""Kiro Crew scheduled job for WattGeist Night Watch (a `script` cron: deterministic Python, no model call).

Crew stores the absolute path of this file and calls run(ctx) in a sandboxed child process whose working directory
is a per-run scratch folder, so every path here is derived from this file's own location, never from the cwd.

The heavy lifting runs in the bundled backend through `uv run wattgeist-nightwatch`, which keeps the backend's
dependencies out of the gateway's interpreter. The result is delivered through Crew:
- a haunted night raises Report(message): Crew posts it to the app's notification channel and the job keeps running;
- a quiet night raises Skip(): nothing is posted, the job fires again tomorrow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from kiro_crew.cron_script import Report, Skip

APP_ROOT = Path(__file__).resolve().parent.parent
# Same default data directory as bin/mcp_launcher.py: the octopus-home this job writes must be readable by the
# night-watch agent through MCP, or the "Was last night haunted?" command cannot find it.
SHARED_DATA_DIR = Path.home() / ".wattgeist"
# A household with enough history to show a haunted night when no Octopus credentials are configured yet
DEMO_HOUSEHOLD = "haunted-semi"


def _uv() -> str:
    for candidate in (shutil.which("uv"), str(Path.home() / ".local/bin/uv"), str(Path.home() / ".cargo/bin/uv")):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("uv is required to run WattGeist Night Watch (https://docs.astral.sh/uv/)")


def run(ctx) -> None:
    env = dict(os.environ)
    env.setdefault("WATTGEIST_DATA_DIR", str(SHARED_DATA_DIR))
    env["WATTGEIST_DISABLE_AI"] = "1"
    args = [_uv(), "run", "--quiet", "--project", str(APP_ROOT / "backend"), "wattgeist-nightwatch", "--json"]
    if env.get("OCTOPUS_API_KEY") and env.get("OCTOPUS_MPAN") and env.get("OCTOPUS_SERIAL"):
        args += ["--refresh-octopus", "--household", "octopus-home"]
    else:
        # Demo mode looks back over the whole demo year so a first run has something to show
        args += ["--household", env.get("WATTGEIST_HOUSEHOLD", DEMO_HOUSEHOLD), "--lookback", "400"]
    proc = subprocess.run(args, capture_output=True, text=True, env=env, timeout=200, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-500:] or f"night watch exited {proc.returncode}")
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    if not result["new_haunted"]:
        raise Skip()
    raise Report(result["message"])
