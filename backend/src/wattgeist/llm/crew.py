"""Kiro Crew agent runner: every AI step in WattGeist is a Kiro Crew agent from the wattgeist-night-watch app.

The web backend never talks to a model provider itself. It runs `kirocrew chat --agent <app>--<agent> -m <message>`,
the non-interactive single-message mode of the Kiro Crew CLI, and reads the agent's answer from stdout as it streams.
Agents, prompts and MCP tool grants live in crew-app/wattgeist-night-watch/agents/*.json, so Kiro Crew owns the model
choice, sign-in and tool loop. Without a kirocrew binary llm_available() is False: import falls back to heuristics
only, the Q&A endpoint returns 503, everything else works.
"""

from __future__ import annotations

import codecs
import logging
import os
import selectors
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from .. import service

log = logging.getLogger(__name__)

# Default Crew app name. Crew names an app's agent "<app>--<name in the agent file>", as in the crew-app README
DEFAULT_APP = "wattgeist-night-watch"
SEANCE_AGENT = "seance"
FORMAT_REVIEW_AGENT = "format-reviewer"
# Keep only the tail of stderr for errors: a failing kirocrew prints a full traceback there, which can be large
_STDERR_TAIL_BYTES = 8192


class CrewError(RuntimeError):
    """kirocrew is missing, timed out or exited non-zero. The message is for the log, not shown to users as is."""


def kirocrew_bin() -> str | None:
    """Locate the kirocrew executable.

    When WATTGEIST_KIROCREW is set, only that path is used (tests point it at a fake kirocrew script; deployments can
    point it at a non-standard install). Otherwise look on PATH, then in ~/.local/bin, where the official installer
    puts it, because a backend started as a service often runs without that directory on PATH.
    """
    explicit = os.environ.get("WATTGEIST_KIROCREW")
    candidates = [explicit] if explicit else [shutil.which("kirocrew"), str(Path.home() / ".local/bin/kirocrew")]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def agent_id(name: str) -> str:
    return f"{os.environ.get('WATTGEIST_CREW_APP', DEFAULT_APP)}--{name}"


def llm_available() -> bool:
    # WATTGEIST_DISABLE_AI=1 is a hard switch: the MCP server and the cron job set it so they never start an agent
    if os.environ.get("WATTGEIST_DISABLE_AI") == "1":
        return False
    return kirocrew_bin() is not None


def _explain(stderr: bytes, returncode: int | None) -> str:
    text = stderr.decode("utf-8", "replace").strip()
    # Being signed out of Kiro is the most common set-up problem (AcpAuthRequired), so it gets an actionable message
    if "Not signed in" in text or "AcpAuthRequired" in text:
        return "Kiro Crew is not signed in to Kiro"
    last = text.splitlines()[-1] if text else ""
    return last.lstrip("❌ ").strip() or f"kirocrew exited with code {returncode}"


def stream_agent(agent: str, message: str, timeout: float) -> Iterator[str]:
    """Run a Crew agent and yield its answer text chunk by chunk.

    - Source: `kirocrew chat -m` prints only the model's text chunks to stdout; errors go to stderr with exit code 1.
      Tool calls are not printed and cannot be approved by a person in this non-interactive mode, so every tool the
      agent may use must be pre-approved in the agent JSON's allowedTools.
    - stdout and stderr are read together with selectors: reading stdout alone would deadlock once the child blocks
      on a full stderr pipe.
    - Termination: after both pipes reach EOF the exit code is checked; exceeding `timeout` (for the whole call, not
      one read) is a failure.
    - If the caller stops iterating (for example the browser disconnects and StreamingResponse closes the
      generator), `finally` kills the child so no agent session is left running.
    """
    exe = kirocrew_bin()
    if exe is None:
        raise CrewError("kirocrew not found")
    data = service.data_dir()
    env = {
        **os.environ,
        # Hand the web backend's data dir to the agent's MCP server so uploaded homes are visible to it
        # (bin/mcp_launcher.py keeps an explicit WATTGEIST_DATA_DIR)
        "WATTGEIST_DATA_DIR": str(data),
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.Popen(
        [exe, "chat", "--agent", agent_id(agent), "-m", message],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        # Not the repository root: kiro-cli loads .kiro/ steering from its working directory, which is for development
        # and must not reach the product agent's context
        cwd=data,
    )
    assert proc.stdout is not None and proc.stderr is not None
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    sel.register(proc.stderr, selectors.EVENT_READ)
    # Incremental decoding: a multi-byte UTF-8 character can be split across two reads
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    err = bytearray()
    deadline = time.monotonic() + timeout
    try:
        while sel.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CrewError(f"agent {agent} timed out after {timeout:.0f} s")
            for key, _ in sel.select(remaining):
                chunk = os.read(key.fd, 4096)
                if not chunk:
                    sel.unregister(key.fileobj)
                elif key.fileobj is proc.stdout:
                    if text := decoder.decode(chunk):
                        yield text
                else:
                    err += chunk
                    del err[:-_STDERR_TAIL_BYTES]
        if tail := decoder.decode(b"", final=True):
            yield tail
        rc = proc.wait(timeout=10)
        if rc != 0:
            log.warning("kirocrew agent %s failed (%s): %s", agent, rc, err.decode("utf-8", "replace")[-2000:])
            raise CrewError(_explain(bytes(err), rc))
    finally:
        sel.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()


def run_agent(agent: str, message: str, timeout: float) -> str:
    """Non-streaming call: collect the whole answer, for the import review, which needs one complete JSON reply."""
    return "".join(stream_agent(agent, message, timeout))
