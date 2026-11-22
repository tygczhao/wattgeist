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
# 数据目录与 WattGeist Web 后端共用（默认 ~/.wattgeist，与 service.data_dir() 的默认值一致）。
# 原因：Web 端的 Séance 和导入复核改由本 app 的 Kiro Crew agent 实现，agent 通过本 MCP server 读取家庭数据；
# 若仍用 app 私有的 data 目录，用户在网页上传的家庭对 agent 不可见，只能看到内置 demo。
# 显式设置 WATTGEIST_DATA_DIR 时以它为准（Web 后端调用 kirocrew 时也会传同一个值）。
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
