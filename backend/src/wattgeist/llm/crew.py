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

# 默认的 Crew app 名；agent 在 Crew 里的全名是 "<app>--<agent文件里的name>"（与 crew-app README 中 kirocrew chat 的示例一致）
DEFAULT_APP = "wattgeist-night-watch"
SEANCE_AGENT = "seance"
FORMAT_REVIEW_AGENT = "format-reviewer"
# stderr 只保留尾部用于报错：kirocrew 失败时会把完整 traceback 打到 stderr，全部保留既没用也可能很大
_STDERR_TAIL_BYTES = 8192


class CrewError(RuntimeError):
    """kirocrew 不可用、超时或以非零码退出。message 面向日志，不直接展示给用户。"""


def kirocrew_bin() -> str | None:
    """定位 kirocrew 可执行文件。

    WATTGEIST_KIROCREW 显式指定时只认它（测试用它指向假的 kirocrew 脚本，部署时可指向非标准安装位置）；
    否则查 PATH，再查官方安装脚本的默认位置 ~/.local/bin，因为以服务方式启动的后端 PATH 往往不含该目录。
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
    # WATTGEIST_DISABLE_AI=1 是硬开关：MCP server 和定时任务都会设置它，防止它们在 Crew 里间接触发 agent 调用
    if os.environ.get("WATTGEIST_DISABLE_AI") == "1":
        return False
    return kirocrew_bin() is not None


def _explain(stderr: bytes, returncode: int | None) -> str:
    text = stderr.decode("utf-8", "replace").strip()
    # 未登录 Kiro 是最常见的部署问题（kirocrew 抛 AcpAuthRequired），单独给出可操作的提示
    if "Not signed in" in text or "AcpAuthRequired" in text:
        return "Kiro Crew is not signed in to Kiro"
    last = text.splitlines()[-1] if text else ""
    return last.lstrip("❌ ").strip() or f"kirocrew exited with code {returncode}"


def stream_agent(agent: str, message: str, timeout: float) -> Iterator[str]:
    """运行一个 Crew agent 并逐块产出其回答文本。

    - 数据来源：kirocrew chat -m 只把模型文本块原样打印到 stdout，错误写 stderr 并以退出码 1 结束；工具调用不打印，
      非交互模式下也无法人工批准，所以 agent 能用的工具必须在 agent JSON 的 allowedTools 中预先放行。
    - 同时用 selectors 读 stdout 和 stderr：只读 stdout 时，stderr 管道写满会让子进程阻塞，形成死锁。
    - 终止条件：两个管道都 EOF 后检查退出码；超过 timeout（整次调用的总时长，而非单次读取）则视为失败。
    - 调用方中途放弃迭代（如浏览器断开导致 StreamingResponse 关闭生成器）时，finally 会杀掉子进程，避免遗留 agent 会话。
    """
    exe = kirocrew_bin()
    if exe is None:
        raise CrewError("kirocrew not found")
    data = service.data_dir()
    env = {
        **os.environ,
        # 把 Web 后端的数据目录传给 agent 的 MCP server，使网页上传的家庭对 agent 可见（launcher 用 setdefault 读取它）
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
        # 不在仓库根目录运行：kiro-cli 会加载工作目录下的 .kiro/ steering，那是给开发用的，不应混进产品 agent 的上下文
        cwd=data,
    )
    assert proc.stdout is not None and proc.stderr is not None
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    sel.register(proc.stderr, selectors.EVENT_READ)
    # 增量解码：一个多字节 UTF-8 字符可能被拆在两次 read 之间，逐块直接 decode 会产生乱码
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
    """非流式调用：收集完整回答，供导入复核这类需要整段 JSON 的场景使用。"""
    return "".join(stream_agent(agent, message, timeout))
