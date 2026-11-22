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

# 导入是同步请求，用户在页面上等待；复核超时后 pipeline 会保留启发式结果，所以这里宁可短一些
REVIEW_TIMEOUT_S = 120.0


class _Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: ParseConfig
    notes: list[str]


def _extract_json(text: str) -> dict:
    """从 agent 回答里取出 JSON 对象。

    原先直连模型 API 时由 structured outputs 保证输出符合 schema；Crew agent 只能靠 prompt 约束，
    模型偶尔仍会包一层 ``` 代码块或前后带一句话，所以取第一个 "{" 到最后一个 "}" 之间的内容再解析。
    解析或校验失败直接抛异常：pipeline 会捕获并保留启发式结果（需求 3.4）。
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
            # schema 随请求发送而不是写死在 agent prompt 里：ParseConfig 一改，agent 看到的字段约束自动同步
            "reply_schema": _Proposal.model_json_schema(),
        }
        reply = run_agent(FORMAT_REVIEW_AGENT, json.dumps(payload, ensure_ascii=False), REVIEW_TIMEOUT_S)
        proposal = _Proposal.model_validate(_extract_json(reply))
        # The file type comes from magic bytes and the agent may not change it; doing so would only make the parser read the file the wrong way
        cfg = proposal.config.model_copy(update={"file_kind": current.file_kind})
        return cfg, [n for n in proposal.notes if n.strip()][:6]
