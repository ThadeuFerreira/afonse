"""
Unit tests for music_teacher_ai/pipeline/reporter.py.
No database or external API required.
"""
import json
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_report(tmp_path, monkeypatch, stage="test"):
    monkeypatch.setattr("music_teacher_ai.config.settings.REPORTS_DIR", tmp_path / "reports")
    # Re-patch the module-level import inside reporter
    import music_teacher_ai.pipeline.reporter as mod
    monkeypatch.setattr(mod, "REPORTS_DIR", tmp_path / "reports")
    from music_teacher_ai.pipeline.reporter import PipelineReport
    return PipelineReport(stage)


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------

def test_increment_basic(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.increment("downloaded")
    report.increment("downloaded")
    report.increment("failed")
    assert report._counters["downloaded"] == 2
    assert report._counters["failed"] == 1


def test_increment_by(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.increment("total", by=50)
    assert report._counters["total"] == 50


def test_set_counter(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.set("total", 100)
    report.set("total", 200)
    assert report._counters["total"] == 200


def test_increment_from_zero(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.increment("new_key")
    assert report._counters["new_key"] == 1


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_add_event(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.add_event("rate_limit", new_workers=2, wait_seconds=60)
    assert len(report._events) == 1
    ev = report._events[0]
    assert ev["message"] == "rate_limit"
    assert ev["new_workers"] == 2
    assert ev["wait_seconds"] == 60
    assert "time" in ev


def test_add_multiple_events(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.add_event("start")
    report.add_event("backoff", workers=1)
    report.add_event("hard_stop")
    assert len(report._events) == 3


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def test_add_error(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    report.add_error(song_id=1, error="404 not found")
    assert len(report._errors) == 1
    assert report._errors[0]["song_id"] == 1
    assert "time" in report._errors[0]


def test_error_cap(tmp_path, monkeypatch):
    from music_teacher_ai.pipeline import reporter as mod
    cap = mod._MAX_INLINE_ERRORS

    report = make_report(tmp_path, monkeypatch)
    for i in range(cap + 50):
        report.add_error(song_id=i, error="oops")

    assert len(report._errors) == cap


# ---------------------------------------------------------------------------
# save() — JSON structure
# ---------------------------------------------------------------------------

def test_save_creates_file(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch, stage="lyrics")
    path = report.save()
    assert path.exists()
    assert path.suffix == ".json"
    assert "lyrics_" in path.name


def test_save_json_structure(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch, stage="charts")
    report.set("total", 10)
    report.increment("indexed", by=7)
    report.add_event("done")
    report.add_error(song_id=99, error="fail")

    path = report.save()
    data = json.loads(path.read_text())

    assert data["stage"] == "charts"
    assert "started_at" in data
    assert "finished_at" in data
    assert "duration_seconds" in data
    assert data["total"] == 10
    assert data["indexed"] == 7
    assert len(data["events"]) == 1
    assert len(data["errors"]) == 1


def test_save_duration_is_non_negative(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch)
    path = report.save()
    data = json.loads(path.read_text())
    assert data["duration_seconds"] >= 0


def test_save_empty_report(tmp_path, monkeypatch):
    report = make_report(tmp_path, monkeypatch, stage="vocab")
    path = report.save()
    data = json.loads(path.read_text())
    assert data["stage"] == "vocab"
    assert data["events"] == []
    assert data["errors"] == []
