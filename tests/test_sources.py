"""Tests for source plugins."""

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from self_healing.sources import get_source, list_sources, register_source, get_all_sources
from self_healing.sources.base import FailureSource
from self_healing.sources.logfile import LogFileSource
from self_healing.sources.jsonl import JSONLSource


class TestSourceRegistry:
    """Test the source registry."""

    def test_builtin_sources_registered(self):
        available = list_sources()
        assert "openclaw" in available
        assert "logfile" in available
        assert "jsonl" in available

    def test_get_source_by_name(self):
        source = get_source("logfile")
        assert isinstance(source, LogFileSource)
        assert source.name == "logfile"

    def test_get_unknown_source_raises(self):
        try:
            get_source("nonexistent_source_xyz")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass

    def test_custom_source_registration(self):
        class CustomSource(FailureSource):
            name = "custom_test"
            def scan(self, hours=6):
                return [{"source": "custom", "id": "1", "name": "test",
                         "error": "test error", "timestamp": "now", "severity": "info"}]

        register_source("custom_test", CustomSource)
        assert "custom_test" in list_sources()
        source = get_source("custom_test")
        results = source.scan()
        assert len(results) == 1
        assert results[0]["source"] == "custom"

    def test_get_all_sources_no_config(self):
        sources = get_all_sources()
        assert len(sources) >= 3

    def test_get_all_sources_with_config(self):
        config = {
            "sources": {
                "logfile": {"enabled": True, "paths": ["/tmp/*.log"]},
                "jsonl": {"enabled": False},
            }
        }
        sources = get_all_sources(config)
        names = [s.name for s in sources]
        assert "logfile" in names
        assert "jsonl" not in names


class TestLogFileSource:
    """Test the log file source plugin."""

    def test_scan_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = LogFileSource(paths=[f"{tmpdir}/*.log"])
            results = source.scan(hours=1)
            assert results == []

    def test_scan_log_with_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            log_file.write_text(
                "2026-03-29 10:00:00 INFO Starting up\n"
                "2026-03-29 10:00:01 ERROR Connection failed to database\n"
                "2026-03-29 10:00:02 INFO Retrying...\n"
                "2026-03-29 10:00:03 FATAL Out of memory\n"
            )
            source = LogFileSource(paths=[f"{tmpdir}/*.log"])
            results = source.scan(hours=24)
            assert len(results) == 2
            errors = [r["error"] for r in results]
            assert any("Connection failed" in e for e in errors)
            assert any("Out of memory" in e for e in errors)

    def test_scan_respects_time_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "old.log"
            log_file.write_text("ERROR something broke\n")
            import os
            old_time = time.time() - 86400
            os.utime(log_file, (old_time, old_time))
            source = LogFileSource(paths=[f"{tmpdir}/*.log"])
            results = source.scan(hours=1)
            assert len(results) == 0

    def test_severity_classification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "sev.log"
            log_file.write_text("FATAL crash\nCRITICAL disk full\nERROR bad request\n")
            source = LogFileSource(
                paths=[f"{tmpdir}/*.log"],
                severity_map={"FATAL": "critical", "CRITICAL": "critical", "ERROR": "warning"}
            )
            results = source.scan(hours=24)
            assert any(r["severity"] == "critical" for r in results)

    def test_custom_error_patterns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "custom.log"
            log_file.write_text(
                "level=info msg=all good\n"
                "level=error msg=something broke\n"
                "CUSTOM_ALERT: system down\n"
            )
            source = LogFileSource(
                paths=[f"{tmpdir}/*.log"],
                error_patterns=[r"CUSTOM_ALERT"]
            )
            results = source.scan(hours=24)
            assert len(results) == 1
            assert "CUSTOM_ALERT" in results[0]["error"]

    def test_from_config(self):
        source = LogFileSource.from_config({
            "paths": ["/var/log/*.log"],
            "error_patterns": ["BOOM"],
            "severity_map": {"BOOM": "critical"},
        })
        assert source.paths == ["/var/log/*.log"]
        assert source.severity_map == {"BOOM": "critical"}


class TestJSONLSource:
    """Test the JSONL source plugin."""

    def test_scan_missing_file(self):
        source = JSONLSource(path="/tmp/nonexistent_test_file_12345.jsonl")
        results = source.scan(hours=1)
        assert results == []

    def test_scan_jsonl_with_errors(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            now = datetime.now(timezone.utc).isoformat()
            records = [
                {"message": "Connection timeout to redis", "timestamp": now, "level": "error", "id": "1"},
                {"message": "Disk full on /dev/sda1", "timestamp": now, "level": "fatal", "id": "2"},
                {"message": "All good", "timestamp": now, "level": "info", "id": "3"},
            ]
            for r in records:
                f.write(json.dumps(r) + "\n")
            f.flush()
            source = JSONLSource(path=f.name)
            results = source.scan(hours=1)
            assert len(results) == 3
            severities = {r["id"]: r["severity"] for r in results}
            assert severities["1"] == "warning"
            assert severities["2"] == "critical"
            Path(f.name).unlink()

    def test_scan_respects_time_window(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            old_ts = "2020-01-01T00:00:00+00:00"
            f.write(json.dumps({"message": "old error", "timestamp": old_ts, "level": "error"}) + "\n")
            f.flush()
            source = JSONLSource(path=f.name)
            results = source.scan(hours=1)
            assert len(results) == 0
            Path(f.name).unlink()

    def test_custom_field_names(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            now = datetime.now(timezone.utc).isoformat()
            f.write(json.dumps({"msg": "boom", "ts": now, "sev": "critical", "uid": "abc"}) + "\n")
            f.flush()
            source = JSONLSource(
                path=f.name,
                error_field="msg",
                timestamp_field="ts",
                severity_field="sev",
                id_field="uid",
            )
            results = source.scan(hours=1)
            assert len(results) == 1
            assert results[0]["error"] == "boom"
            assert results[0]["id"] == "abc"
            assert results[0]["severity"] == "critical"
            Path(f.name).unlink()

    def test_epoch_timestamps(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            now_epoch = time.time()
            f.write(json.dumps({"message": "epoch error", "timestamp": now_epoch, "level": "error"}) + "\n")
            f.write(json.dumps({"message": "ms epoch", "timestamp": now_epoch * 1000, "level": "error"}) + "\n")
            f.flush()
            source = JSONLSource(path=f.name)
            results = source.scan(hours=1)
            assert len(results) == 2
            Path(f.name).unlink()

    def test_malformed_lines_skipped(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            now = datetime.now(timezone.utc).isoformat()
            f.write("not json at all\n")
            f.write(json.dumps({"message": "valid", "timestamp": now, "level": "error"}) + "\n")
            f.write("{bad json\n")
            f.flush()
            source = JSONLSource(path=f.name)
            results = source.scan(hours=1)
            assert len(results) == 1
            assert results[0]["error"] == "valid"
            Path(f.name).unlink()

    def test_from_config(self):
        source = JSONLSource.from_config({
            "path": "/tmp/my-errors.jsonl",
            "error_field": "msg",
            "timestamp_field": "ts",
            "severity_field": "sev",
        })
        assert source.path == Path("/tmp/my-errors.jsonl")
        assert source.error_field == "msg"
