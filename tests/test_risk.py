"""Tests for the risk scoring engine in self-heal.py."""

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import importlib.util
spec = importlib.util.spec_from_file_location("self_heal", SKILL_DIR / "scripts" / "self-heal.py")
self_heal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(self_heal)

score_risk = self_heal.score_risk


class TestRiskScoring:
    """Test the risk scoring engine."""

    def test_static_site_low_risk(self):
        """Static site changes should be low risk."""
        result = score_risk("Fix broken HTML in blog post content page")
        assert result["riskScore"] <= 0.5
        assert result["decision"] in ("auto_apply", "apply_with_caution")

    def test_payment_high_risk(self):
        """Payment system changes should be high risk."""
        result = score_risk("Fix Stripe payment processing error in billing module")
        assert result["riskScore"] >= 0.7
        assert result["decision"] in ("human_review", "escalate")

    def test_database_critical_risk(self):
        """Database changes should be critical risk."""
        result = score_risk("Fix database migration that drops user table")
        assert result["riskScore"] >= 0.8
        assert result["decision"] == "escalate"

    def test_cron_job_moderate_risk(self):
        """Cron job fixes should be moderate risk."""
        result = score_risk("Fix broken scheduled cron task for periodic cleanup")
        assert 0.1 <= result["riskScore"] <= 0.6

    def test_unknown_system_default_risk(self):
        """Unknown systems should get moderate default risk."""
        result = score_risk("Fix something in an unknown system xyz123")
        assert result["profile"] == "unknown"
        assert 0.3 <= result["riskScore"] <= 0.7

    def test_retry_reduces_risk(self):
        """Retry fix type should reduce risk."""
        result_retry = score_risk("Fix cron job failure", fix_type="retry")
        result_heal = score_risk("Fix cron job failure", fix_type="heal")
        assert result_retry["riskScore"] < result_heal["riskScore"]

    def test_heal_increases_risk(self):
        """Heal fix type should increase risk vs patch."""
        result_patch = score_risk("Fix static content page", fix_type="patch")
        result_heal = score_risk("Fix static content page", fix_type="heal")
        assert result_heal["riskScore"] > result_patch["riskScore"]

    def test_risk_has_reasoning(self):
        """Risk result should include reasoning."""
        result = score_risk("Fix email notification sending")
        assert "reasoning" in result
        assert len(result["reasoning"]) > 0

    def test_risk_decisions(self):
        """Verify decision thresholds."""
        # Force low risk
        result = score_risk("Fix static HTML blog content page resource", fix_type="retry")
        assert result["riskScore"] <= 0.3 or result["decision"] in ("auto_apply", "apply_with_caution")

    def test_social_media_risk(self):
        """Social media posts are not easily reversible."""
        result = score_risk("Fix Instagram reel posting error")
        assert result["riskScore"] >= 0.4
        assert "reasoning" in result

    def test_config_risk(self):
        """Config changes should be moderate-high risk."""
        result = score_risk("Fix openclaw.json gateway config settings")
        assert result["riskScore"] >= 0.5

    def test_deployment_risk(self):
        """Deploy/git push should be moderate risk."""
        result = score_risk("Fix git push deploy to cloudflare production")
        assert result["riskScore"] >= 0.3

    def test_risk_score_bounds(self):
        """Risk score should always be between 0 and 1."""
        for desc in ["trivial", "payment stripe critical database", "html blog static"]:
            for fix_type in ["retry", "patch", "heal"]:
                result = score_risk(desc, fix_type=fix_type)
                assert 0.0 <= result["riskScore"] <= 1.0
