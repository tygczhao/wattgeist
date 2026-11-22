"""The Kiro Crew agent layer: the backend runs `kirocrew chat --agent ... -m ...` and reads the answer from stdout.

A fake kirocrew script stands in for the real CLI, so these tests need neither a Kiro sign-in nor a model call.
They pin the contract with Kiro Crew (argv, data dir, exit codes, timeout) and the handling of agent replies.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
import types

import pytest

from tests.unit.test_ingest_requirements import _unlabelled_csv
from tests.unit.test_ingest_requirements import truth as truth  # noqa: F401  复用同一个 truth fixture
from wattgeist import service
from wattgeist.ingest.config import ParseConfig
from wattgeist.ingest.pipeline import import_meter_file
from wattgeist.llm import assistant, crew
from wattgeist.llm.parse_assist import CrewFormatAssistant

# 假 kirocrew：把收到的 argv 和关键环境变量写入 FAKE_LOG，再按 FAKE_* 环境变量决定输出、退出码或挂起，
# 模拟真实 CLI 的行为约定：回答走 stdout，错误走 stderr 并以非零码退出
_FAKE = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys, time
    with open(os.environ["FAKE_LOG"], "w") as f:
        json.dump({{"argv": sys.argv[1:], "data_dir": os.environ.get("WATTGEIST_DATA_DIR"), "cwd": os.getcwd()}}, f)
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    for part in json.loads(os.environ.get("FAKE_PARTS", "[]")):
        sys.stdout.write(part)
        sys.stdout.flush()
    sys.stderr.write(os.environ.get("FAKE_STDERR", ""))
    sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
    """
)


@pytest.fixture
def fake_crew(tmp_path, monkeypatch):
    exe = tmp_path / "kirocrew"
    exe.write_text(_FAKE.format(python=sys.executable))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "argv.json"
    monkeypatch.setenv("WATTGEIST_KIROCREW", str(exe))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.delenv("WATTGEIST_DISABLE_AI", raising=False)

    def reply(*parts: str, exit_code: int = 0, stderr: str = "", sleep: float = 0) -> None:
        monkeypatch.setenv("FAKE_PARTS", json.dumps(list(parts)))
        monkeypatch.setenv("FAKE_EXIT", str(exit_code))
        monkeypatch.setenv("FAKE_STDERR", stderr)
        if sleep:
            monkeypatch.setenv("FAKE_SLEEP", str(sleep))

    reply.calls = lambda: json.loads(log.read_text())
    return reply


def test_ai_is_available_only_with_a_kirocrew_binary(fake_crew, monkeypatch, tmp_path):
    assert crew.llm_available()
    monkeypatch.setenv("WATTGEIST_DISABLE_AI", "1")
    assert not crew.llm_available()
    monkeypatch.delenv("WATTGEIST_DISABLE_AI")
    monkeypatch.setenv("WATTGEIST_KIROCREW", str(tmp_path / "missing"))
    assert not crew.llm_available()


def test_agent_runs_through_kirocrew_chat_with_the_shared_data_dir(fake_crew):
    # 多字节字符被拆在两次写出之间，验证增量解码不会产生乱码
    fake_crew("The floor is 1", "20 W 👻", "\n")
    out = list(crew.stream_agent("seance", "hello", timeout=30))
    assert "".join(out) == "The floor is 120 W 👻\n"
    call = fake_crew.calls()
    assert call["argv"] == ["chat", "--agent", "wattgeist-night-watch--seance", "-m", "hello"]
    # agent 的 MCP server 必须读到与 Web 后端相同的数据目录，且不在仓库目录下运行（避免加载开发用 .kiro steering）
    assert call["data_dir"] == str(service.data_dir())
    assert os.path.realpath(call["cwd"]) == os.path.realpath(service.data_dir())


def test_crew_app_name_can_be_overridden(fake_crew, monkeypatch):
    monkeypatch.setenv("WATTGEIST_CREW_APP", "my-fork")
    fake_crew("ok")
    crew.run_agent("format-reviewer", "x", timeout=30)
    assert fake_crew.calls()["argv"][2] == "my-fork--format-reviewer"


def test_signed_out_kiro_becomes_an_actionable_error(fake_crew):
    fake_crew(exit_code=1, stderr="kiro_crew.acp.client.AcpAuthRequired: Not signed in to Kiro.\n")
    with pytest.raises(crew.CrewError, match="not signed in"):
        crew.run_agent("seance", "hi", timeout=30)


def test_a_hung_agent_is_killed_at_the_timeout(fake_crew):
    fake_crew("late", sleep=30)
    with pytest.raises(crew.CrewError, match="timed out"):
        crew.run_agent("seance", "hi", timeout=1)


def _home():
    return types.SimpleNamespace(id="haunted-semi")


def test_seance_streams_text_then_done_and_sends_id_history_and_question(fake_crew, monkeypatch):
    monkeypatch.setattr(service, "household_card", lambda h: {"id": h.id, "always_on_w": 262})
    fake_crew("Your floor ", "is 262 W.")
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Boo."}, {"role": "tool", "content": "x"}]
    events = list(assistant.ask(_home(), "Is that high?", history))
    # 管道可能把两次写出合并成一块，所以只断言事件类型序列和拼接后的文本
    assert {e["type"] for e in events[:-1]} == {"text"} and events[-1] == {"type": "done"}
    assert "".join(e["delta"] for e in events[:-1]) == "Your floor is 262 W."
    msg = fake_crew.calls()["argv"][-1]
    assert "Household id: haunted-semi" in msg
    assert "User: hi\nMedium: Boo." in msg and "tool" not in msg.split("Conversation so far:")[1]
    assert msg.endswith("New question: Is that high?")


def test_seance_failure_is_a_short_message_without_a_traceback(fake_crew, monkeypatch):
    monkeypatch.setattr(service, "household_card", lambda h: {"id": h.id})
    fake_crew(exit_code=1, stderr="Traceback (most recent call last):\n  ...\nAcpAuthRequired: Not signed in to Kiro\n")
    events = list(assistant.ask(_home(), "?", []))
    assert len(events) == 1 and events[0]["type"] == "error"
    assert "Traceback" not in events[0]["message"] and "Kiro Crew" in events[0]["message"]


def test_format_reviewer_reply_is_validated_and_keeps_the_detected_file_kind(fake_crew):
    current = ParseConfig(file_kind="csv", value_column="col_a")
    reply = {"config": {**current.model_dump(), "file_kind": "excel", "value_column": "col_c"}, "notes": ["Read col_c.", " "]}
    # 模型偶尔会包一层代码块并附一句话，解析必须容忍
    fake_crew("Here you go:\n```json\n", json.dumps(reply), "\n```\n")
    cfg, notes = CrewFormatAssistant().propose(["col_a,col_b,col_c"], ["col_a", "col_b", "col_c"], current, ["low"])
    assert cfg.value_column == "col_c" and cfg.file_kind == "csv"
    assert notes == ["Read col_c."]
    sent = json.loads(fake_crew.calls()["argv"][-1])
    assert sent["file_preview"] == ["col_a,col_b,col_c"] and "properties" in sent["reply_schema"]


def test_format_reviewer_prose_reply_is_rejected(fake_crew):
    fake_crew("I think the unit is kWh.")
    with pytest.raises(ValueError):
        CrewFormatAssistant().propose([], [], ParseConfig(file_kind="csv"), [])


def test_crew_review_end_to_end_through_the_import_pipeline(fake_crew, truth):  # noqa: F811
    """Requirement 3.3 with the real agent adapter: the reviewer's JSON reply wins when it scores higher."""
    data = _unlabelled_csv(truth)
    heuristic = import_meter_file(data, "unlabelled.csv", "Europe/London").result.config
    fixed = {**heuristic.model_dump(), "value_column": "col_c", "unit": "kWh"}
    fake_crew(json.dumps({"config": fixed, "notes": ["Read col_c as kWh."]}))
    outcome = import_meter_file(data, "unlabelled.csv", "Europe/London", assistant=CrewFormatAssistant())
    assert outcome.source == "ai" and outcome.result.config.value_column == "col_c"
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)


def test_unusable_crew_reply_leaves_the_heuristic_result(fake_crew, truth):  # noqa: F811
    """Requirement 3.4 with the real agent adapter: a failed agent run never breaks the import."""
    data = _unlabelled_csv(truth)
    fake_crew(exit_code=1, stderr="boom")
    outcome = import_meter_file(data, "unlabelled.csv", "Europe/London", assistant=CrewFormatAssistant())
    assert outcome.source != "ai" and outcome.result is not None
