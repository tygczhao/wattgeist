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
# 一次回答的总时长上限：包含 kirocrew 启动、MCP server 冷启动（uv run）和多轮工具调用；原来的“最多 6 轮工具”
# 由 Kiro Crew 的 agent 循环负责，这里只用总时长兜底，防止 agent 失控占住一个请求
ANSWER_TIMEOUT_S = 240.0


def _message(h: service.Household, question: str, history: list[dict]) -> str:
    """拼出发给 seance agent 的单条消息。

    kirocrew chat -m 每次都是新会话，没有多轮记忆，所以由浏览器带回的历史在这里转成文字记录附在问题前。
    household id 必须明确给出：agent 调 MCP 工具时要用它，而 MCP 里同时有 demo 和用户上传的多个家庭。
    历史和问题都是用户可控文本，agent 的 prompt 已声明这些内容只是数据、不是指令。
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
        # 具体原因只写日志；给用户的文案保持简短，不暴露本机路径或 traceback（需求：失败时不返回堆栈）
        log.warning("seance agent failed: %s", exc)
        hint = " (sign in to Kiro in Kiro Crew)" if "not signed in" in str(exc) else ""
        yield {"type": "error", "message": f"The medium could not reach the other side{hint}."}
        return
    yield {"type": "done"}
