"""Acceptance tests for import requirements that the per-format round trips in test_ingest_formats.py do not cover.

Each test names the requirement from .kiro/specs/meter-import/requirements.md it checks:
file-kind detection from content (1.1), multi-meter selection (2.7), when the reviewer is consulted at all (3.1),
what it is allowed to see (3.2), when its proposal wins (3.3) and what happens when it fails (3.4),
and the upload size limit (4.1).
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests import fixtures as fx
from wattgeist import api, service
from wattgeist.ingest.pipeline import AI_REVIEW_BELOW, import_meter_file
from wattgeist.ingest.table import detect_file_kind


@pytest.fixture(scope="module")
def truth():
    """Two months of half-hourly truth: long enough to score well, short enough to keep these tests quick."""
    return fx.truth_series(start="2024-01-01", end="2024-02-29 23:30", tz="Europe/London")


# ---------- Requirement 1.1: detect the file kind from the content, not only the extension ----------


def test_csv_is_detected_when_the_name_says_xlsx(truth):
    """Sheets exported as CSV are often still named .xlsx; a real .xlsx would start with the PK zip magic."""
    data = fx.octopus_csv(truth)
    assert detect_file_kind(data, "consumption.xlsx") == "csv"
    outcome = import_meter_file(data, "consumption.xlsx", "Europe/London")
    assert outcome.error is None, outcome.error
    assert outcome.result.config.file_kind == "csv"
    assert outcome.result.report.score >= 95
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)


def test_csv_is_detected_when_the_name_says_txt(truth):
    data = fx.octopus_csv(truth)
    assert detect_file_kind(data, "consumption.txt") == "csv"
    outcome = import_meter_file(data, "consumption.txt", "Europe/London")
    assert outcome.error is None, outcome.error
    assert outcome.result.report.score >= 95


def test_xlsx_is_detected_when_the_name_says_csv(truth):
    """A workbook renamed .csv: the zip magic bytes decide, so it is read as a spreadsheet, not as text."""
    data = fx.excel_bytes(truth)
    assert detect_file_kind(data, "meter.csv") == "excel"
    outcome = import_meter_file(data, "meter.csv", "Europe/London")
    assert outcome.error is None, outcome.error
    assert outcome.result.config.file_kind == "excel"
    assert outcome.result.report.score >= 95
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)


def test_xlsx_without_an_extension_is_still_detected(truth):
    assert detect_file_kind(fx.excel_bytes(truth), "export") == "excel"


def test_green_button_xml_is_detected_when_the_name_says_csv(truth):
    """An ESPI feed is recognised by its XML root, so a renamed .csv is parsed as Green Button, not as a table."""
    data = fx.green_button_xml(truth, solar_export=False)
    assert detect_file_kind(data, "feed.csv") == "greenbutton_xml"
    outcome = import_meter_file(data, "feed.csv", "Europe/London")
    assert outcome.error is None, outcome.error
    assert outcome.result.config.file_kind == "greenbutton_xml"
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=2e-3)


# ---------- Requirement 2.3: an offset in the file wins over the configured time zone ----------


def test_offsets_in_the_file_override_the_configured_timezone(truth):
    """Octopus stamps carry +00:00 / +01:00, so the household's zone must not move a single reading."""
    data = fx.octopus_csv(truth)
    right = import_meter_file(data, "consumption.csv", "Europe/London").result
    wrong_zone = import_meter_file(data, "consumption.csv", "America/New_York").result
    assert wrong_zone.series.energy_kwh.index[0] == truth.index[0].tz_convert("UTC")
    pd.testing.assert_series_equal(wrong_zone.series.energy_kwh, right.series.energy_kwh)
    # The configured zone is still used for analysis that depends on the local clock
    assert wrong_zone.series.timezone == "America/New_York"


# ---------- Requirement 2.7: several meters in one file ----------


def _multi_meter_csv(t: pd.Series, counts: dict[str, int]) -> bytes:
    """One file holding several meters, rows interleaved in timestamp order so file order does not favour any meter.

    Each meter id gets the first n readings of the truth, so the meter with the most readings is the only one
    whose total equals the whole truth series.
    """
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for meter_id, n in counts.items():
        rows.extend((ts, meter_id, v) for ts, v in t.iloc[:n].items())
    rows.sort(key=lambda r: (r[0], r[1]))
    lines = ["Meter ID,Timestamp,kWh"]
    lines += [f"{meter_id},{ts:%Y-%m-%d %H:%M},{v:.5f}" for ts, meter_id, v in rows]
    return ("\n".join(lines) + "\n").encode()


def test_multi_meter_file_imports_the_largest_meter_and_lists_them_all(truth):
    full = len(truth)
    data = _multi_meter_csv(truth, {"MTR-0001": full // 2, "MTR-0002": full // 4, "MTR-0003": full})
    outcome = import_meter_file(data, "meters.csv", "Europe/London")
    assert outcome.error is None, outcome.error
    r = outcome.result
    # MTR-0003 has the most readings although MTR-0001 appears first in the file and sorts first
    assert r.config.meter_id_column == "Meter ID"
    assert r.config.meter_id == "MTR-0003"
    assert r.series.meter_id == "MTR-0003"
    # All three are listed, most readings first, so the user can switch meter
    assert r.meter_ids == ["MTR-0003", "MTR-0001", "MTR-0002"]
    assert sorted(outcome.inference.meter_ids) == ["MTR-0001", "MTR-0002", "MTR-0003"]
    assert any("3 meters" in n for n in outcome.notes)
    # Only the chosen meter's readings were imported: no other meter's energy is mixed in
    assert r.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)
    assert r.report.duplicate_timestamps == 0
    assert r.report.score >= 95


# ---------- Requirements 3.2-3.4: the AI reviewer ----------


def _unlabelled_csv(t: pd.Series) -> bytes:
    """A file whose column names say nothing: col_a is a meter serial, col_b the timestamp, col_c the reading in kWh.

    The heuristic picks the first numeric column (col_a), which makes the median power implausible and the score low,
    so the pipeline asks the reviewer. The correct reading of the file is value_column=col_c in kWh.
    """
    lines = ["col_a,col_b,col_c"]
    lines += [f"445566,{ts:%Y-%m-%d %H:%M},{v:.5f}" for ts, v in t.items()]
    return ("\n".join(lines) + "\n").encode()


class _RecordingAssistant:
    """Stub reviewer: records exactly what the pipeline sent it and proposes no change."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def propose(self, preview, columns, current, problems):
        self.calls.append(
            {"preview": list(preview), "columns": list(columns), "current": current, "problems": list(problems)}
        )
        return current, []


class _FixingAssistant:
    """Stub reviewer that reads the right column, which scores strictly higher than the heuristic guess."""

    def propose(self, preview, columns, current, problems):
        return current.model_copy(update={"value_column": "col_c", "unit": "kWh"}), ["Read col_c as kWh."]


class _FailingAssistant:
    """Stub reviewer that fails the way a real one can: network error, rate limit, refusal, unusable output."""

    def propose(self, preview, columns, current, problems):
        raise RuntimeError("rate limited")


def _compact_stamp_csv(t: pd.Series) -> bytes:
    """A file whose only timestamp is a compact digit stamp (YYYYMMDDHHMM), which no built-in format matches.

    The heuristic reads that column as a number, so it identifies no timestamp at all and the parse raises instead
    of scoring badly. The correct reading is timestamp_column='Read time' with datetime_format='%Y%m%d%H%M'.
    """
    lines = ["Read time,Consumption (kWh)"]
    lines += [f"{ts:%Y%m%d%H%M},{v:.5f}" for ts, v in t.items()]
    return ("\n".join(lines) + "\n").encode()


class _StampFixingAssistant:
    """Stub reviewer that names the timestamp column and its format, so its config parses where the heuristic's raised."""

    def __init__(self) -> None:
        self.problems: list[str] = []

    def propose(self, preview, columns, current, problems):
        self.problems = list(problems)
        update = {"timestamp_column": "Read time", "datetime_format": "%Y%m%d%H%M"}
        return current.model_copy(update=update), ["'Read time' is a YYYYMMDDHHMM stamp."]


class _UnparsableProposalAssistant:
    """Stub reviewer whose config is a valid ParseConfig but still wrong: this format matches none of the stamps."""

    def propose(self, preview, columns, current, problems):
        update = {"timestamp_column": "Read time", "datetime_format": "%Y-%m-%d %H:%M"}
        return current.model_copy(update=update), ["Timestamps look like ISO 8601."]


def test_assistant_sees_only_the_first_25_lines(truth):
    """Requirement 3.2: the reviewer receives at most 25 preview lines and the column names, never the whole file."""
    data = _unlabelled_csv(truth)
    lines = data.decode().splitlines()
    assistant = _RecordingAssistant()
    outcome = import_meter_file(data, "unlabelled.csv", "Europe/London", assistant=assistant)
    assert outcome.ai_used
    assert len(assistant.calls) == 1
    sent = assistant.calls[0]
    assert sent["preview"] == lines[:25]
    assert len(sent["preview"]) == 25
    assert sent["columns"] == ["col_a", "col_b", "col_c"]
    # Nothing from beyond the preview reaches the assistant: not the later rows, not the end of the file
    body = "\n".join(sent["preview"])
    for later in lines[25:]:
        assert later not in body
    assert len(lines) > 2000
    assert len(body) < len(data) / 10


def test_higher_scoring_ai_config_is_adopted(truth):
    """Requirement 3.3: a proposal that parses the file better replaces the heuristic reading."""
    data = _unlabelled_csv(truth)
    heuristic = import_meter_file(data, "unlabelled.csv", "Europe/London")
    assert heuristic.result.config.value_column == "col_a"
    assert heuristic.result.report.score < 90, heuristic.result.report

    outcome = import_meter_file(data, "unlabelled.csv", "Europe/London", assistant=_FixingAssistant())
    assert outcome.ai_used
    assert outcome.source == "ai"
    assert outcome.result.config.value_column == "col_c"
    assert outcome.result.config.unit == "kWh"
    assert outcome.result.report.score > heuristic.result.report.score
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)
    assert outcome.ai_notes == ["Read col_c as kWh."]


def test_failing_assistant_leaves_the_heuristic_result_in_place(truth):
    """Requirement 3.4: when the reviewer raises, the import still returns the heuristic reading."""
    data = _unlabelled_csv(truth)
    heuristic = import_meter_file(data, "unlabelled.csv", "Europe/London")
    outcome = import_meter_file(data, "unlabelled.csv", "Europe/London", assistant=_FailingAssistant())
    assert outcome.error is None
    assert outcome.source == "heuristic"
    assert not outcome.ai_used
    assert outcome.ai_notes == []
    assert outcome.result.config == heuristic.result.config
    assert outcome.result.report.score == heuristic.result.report.score
    assert outcome.notes == heuristic.notes


def test_review_is_requested_when_the_heuristic_parse_fails_outright(truth):
    """Requirement 3.1: a failed parse triggers the review, and with no heuristic result to beat the proposal is adopted.

    The other two triggers (a low score, an ambiguity) are covered above; this is the best-is-None branch, where
    there is no score to compare against.
    """
    data = _compact_stamp_csv(truth)
    heuristic = import_meter_file(data, "stamps.csv", "Europe/London")
    assert heuristic.result is None
    assert heuristic.error is not None
    assert any("no timestamp column" in a.lower() for a in heuristic.inference.ambiguities)

    assistant = _StampFixingAssistant()
    outcome = import_meter_file(data, "stamps.csv", "Europe/London", assistant=assistant)
    # The reviewer is told the parse failed, not just that the score was low
    assert any("Parsing failed" in p for p in assistant.problems)
    assert outcome.ai_used
    assert outcome.source == "ai"
    assert outcome.error is None
    assert outcome.ai_notes == ["'Read time' is a YYYYMMDDHHMM stamp."]
    assert outcome.result.config.datetime_format == "%Y%m%d%H%M"
    assert outcome.result.report.score >= 95, outcome.result.report
    assert outcome.result.series.energy_kwh.sum() == pytest.approx(truth.sum(), rel=1e-3)
    assert outcome.result.series.energy_kwh.index[0] == truth.index[0].tz_convert("UTC")


def test_failed_heuristic_and_unparsable_proposal_give_an_error_not_a_crash(truth):
    """Requirement 3.1/3.4: when neither config can read the file the import returns an error the user can act on."""
    data = _compact_stamp_csv(truth)
    outcome = import_meter_file(data, "stamps.csv", "Europe/London", assistant=_UnparsableProposalAssistant())
    assert outcome.result is None
    assert outcome.error is not None
    # The reviewer was consulted and its failure is reported next to the heuristic's, so neither is silently swallowed
    assert outcome.ai_used
    assert outcome.ai_notes and "could not be parsed" in outcome.ai_notes[0]


def test_green_button_xml_is_never_sent_to_the_reviewer(truth):
    """Requirement 3.1: an ESPI feed carries its own units and UTC stamps, so there is nothing for a reviewer to guess.

    The feed below is three days long, which scores below the review threshold. For a CSV that would start a review;
    for XML the pipeline must not call the assistant at all, so no meter data leaves the machine.
    """
    short = truth.iloc[: 48 * 3]
    data = fx.green_button_xml(short, solar_export=False)
    assistant = _RecordingAssistant()
    outcome = import_meter_file(data, "feed.xml", "Europe/London", assistant=assistant)
    assert outcome.result.report.score < AI_REVIEW_BELOW, outcome.result.report
    assert assistant.calls == []
    assert not outcome.ai_used
    assert outcome.source == "heuristic"
    assert outcome.ai_notes == []


def test_an_unreadable_green_button_feed_is_not_sent_to_the_reviewer_either(truth):
    """The guard must sit before the review, not inside the score comparison: a failed XML parse stays local too."""
    data = fx.green_button_xml(truth.iloc[:1], solar_export=False)
    assistant = _RecordingAssistant()
    outcome = import_meter_file(data, "feed.xml", "Europe/London", assistant=assistant)
    assert outcome.result is None
    assert outcome.error is not None
    assert assistant.calls == []
    assert not outcome.ai_used


# ---------- Requirement 4.1: reject uploads over 60 MB ----------


@pytest.fixture
def client():
    """The app without its lifespan: the size check runs before any household work, so skip loading demo data."""
    return TestClient(api.app)


@pytest.mark.parametrize("endpoint", ["/api/households", "/api/import/preview"])
def test_oversized_upload_is_rejected_with_413(client, monkeypatch, endpoint):
    # Patch the limit rather than building 60 MB of test data; the API reads one byte past it to detect the overflow
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024)
    response = client.post(
        endpoint,
        files={"file": ("big.csv", b"x" * 2048, "text/csv")},
        data={"name": "Big home", "timezone": "Europe/London", "use_ai": "false"},
    )
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_upload_within_the_limit_is_not_rejected_for_size(client, monkeypatch):
    """Control for the test above: under the limit the request gets past the size check and fails on the content instead."""
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024)
    response = client.post(
        "/api/households",
        files={"file": ("small.csv", b"hello\nworld\n", "text/csv")},
        data={"name": "Small home", "timezone": "Europe/London", "use_ai": "false"},
    )
    assert response.status_code == 422


def test_service_layer_also_refuses_an_oversized_upload(monkeypatch):
    """MCP and other callers do not go through the API, so the limit is enforced in the service layer too."""
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 1024)
    with pytest.raises(ValueError, match="larger than"):
        service.import_upload(b"x" * 2048, "big.csv", "Europe/London", "Big home")
