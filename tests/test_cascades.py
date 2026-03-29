"""Tests for cascading failure detection."""

from datetime import datetime, timezone, timedelta

from self_healing.scanner import detect_cascades, merge_cascade_signatures, CASCADE_SIGNATURES


class TestCascadeDetection:
    """Test cascading failure detection."""

    def test_no_cascade_single_failure(self):
        failures = [
            {"source": "cron", "name": "job1", "error": "Something broke",
             "timestamp": datetime.now(timezone.utc).isoformat(), "severity": "warning"}
        ]
        assert len(detect_cascades(failures)) == 0

    def test_no_cascade_empty(self):
        assert detect_cascades([]) == []

    def test_gateway_down_cascade(self):
        now = datetime.now(timezone.utc).isoformat()
        failures = [
            {"source": "cron", "name": "job1", "error": "ECONNREFUSED 127.0.0.1:3000",
             "timestamp": now, "severity": "critical"},
            {"source": "cron", "name": "job2", "error": "gateway not responding, ECONNREFUSED",
             "timestamp": now, "severity": "critical"},
            {"source": "cron", "name": "job3", "error": "RPC call failed to gateway",
             "timestamp": now, "severity": "critical"},
        ]
        cascades = detect_cascades(failures)
        assert len(cascades) >= 1
        sig_cascades = [c for c in cascades if c["type"] == "signature"]
        assert any(c["name"] == "gateway_down" for c in sig_cascades)

    def test_disk_full_cascade(self):
        now = datetime.now(timezone.utc).isoformat()
        failures = [
            {"source": "cron", "name": "backup", "error": "No space left on device",
             "timestamp": now, "severity": "critical"},
            {"source": "logfile", "name": "app.log", "error": "ENOSPC: write failed",
             "timestamp": now, "severity": "critical"},
        ]
        cascades = detect_cascades(failures)
        sig_cascades = [c for c in cascades if c["type"] == "signature"]
        assert any(c["name"] == "disk_full" for c in sig_cascades)

    def test_time_proximity_cascade(self):
        now = datetime.now(timezone.utc)
        failures = [
            {"source": "cron", "name": "job1", "error": "Unique error alpha",
             "timestamp": now.isoformat(), "severity": "warning"},
            {"source": "cron", "name": "job2", "error": "Unique error beta",
             "timestamp": (now + timedelta(minutes=2)).isoformat(), "severity": "warning"},
            {"source": "cron", "name": "job3", "error": "Unique error gamma",
             "timestamp": (now + timedelta(minutes=4)).isoformat(), "severity": "warning"},
        ]
        cascades = detect_cascades(failures)
        time_cascades = [c for c in cascades if c["type"] == "time_proximity"]
        assert len(time_cascades) >= 1
        assert time_cascades[0]["count"] == 3

    def test_no_time_cascade_spread_out(self):
        now = datetime.now(timezone.utc)
        failures = [
            {"source": "cron", "name": "job1", "error": "Error X",
             "timestamp": now.isoformat(), "severity": "warning"},
            {"source": "cron", "name": "job2", "error": "Error Y",
             "timestamp": (now + timedelta(hours=2)).isoformat(), "severity": "warning"},
        ]
        cascades = detect_cascades(failures)
        time_cascades = [c for c in cascades if c["type"] == "time_proximity"]
        assert len(time_cascades) == 0

    def test_mass_cron_failure_cascade(self):
        now = datetime.now(timezone.utc)
        failures = [
            {"source": "cron", "name": f"job{i}", "error": f"Unique error {i}",
             "timestamp": (now + timedelta(hours=i)).isoformat(), "severity": "warning"}
            for i in range(4)
        ]
        cascades = detect_cascades(failures)
        source_cascades = [c for c in cascades if c["type"] == "source_correlation"]
        assert len(source_cascades) >= 1
        assert source_cascades[0]["name"] == "mass_cron_failure"

    def test_auth_expired_cascade(self):
        now = datetime.now(timezone.utc).isoformat()
        failures = [
            {"source": "cron", "name": "api-sync", "error": "401 Unauthorized: token expired",
             "timestamp": now, "severity": "warning"},
            {"source": "subagent", "name": "data-fetch", "error": "Unauthorized: invalid token",
             "timestamp": now, "severity": "warning"},
        ]
        cascades = detect_cascades(failures)
        sig_cascades = [c for c in cascades if c["type"] == "signature"]
        assert any(c["name"] == "auth_expired" for c in sig_cascades)

    def test_custom_cascade_signatures(self):
        custom_sigs = {
            **CASCADE_SIGNATURES,
            "my_service": {
                "patterns": [r"my-service.*down", r"my-service.*unreachable"],
                "description": "My service is down",
                "severity": "critical"
            }
        }
        now = datetime.now(timezone.utc).isoformat()
        failures = [
            {"source": "logfile", "name": "monitor", "error": "my-service is down",
             "timestamp": now, "severity": "critical"},
            {"source": "logfile", "name": "checker", "error": "my-service unreachable on port 8080",
             "timestamp": now, "severity": "critical"},
        ]
        cascades = detect_cascades(failures, cascade_sigs=custom_sigs)
        assert any(c["name"] == "my_service" for c in cascades)

    def test_merge_cascade_signatures(self):
        config = {
            "cascades": {
                "custom_cascade": {
                    "patterns": ["custom.*error"],
                    "description": "Custom cascade",
                    "severity": "warning"
                }
            }
        }
        merged = merge_cascade_signatures(config)
        assert "gateway_down" in merged
        assert "custom_cascade" in merged
