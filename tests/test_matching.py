"""Tests for the smart matching engine in self-heal.py."""

import sys
from pathlib import Path

# Import from scripts/
SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

# We need to import functions from self-heal.py (which has a hyphen in the name)
import importlib.util
spec = importlib.util.spec_from_file_location("self_heal", SKILL_DIR / "scripts" / "self-heal.py")
self_heal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(self_heal)

smart_match = self_heal.smart_match
classify_error = self_heal.classify_error
ngram_overlap = self_heal.ngram_overlap
extract_paths = self_heal.extract_paths


class TestSmartMatch:
    """Test the multi-signal smart matching engine."""

    def test_exact_substring_match(self):
        """Exact substring should score very high."""
        score, signals = smart_match(
            "FileNotFoundError: /tmp/template.json not found",
            "FileNotFoundError: /tmp/template.json not found"
        )
        assert score >= 0.9
        signal_names = [s[0] for s in signals]
        assert "substring" in signal_names

    def test_substring_contained(self):
        """Pattern contained in error text should match."""
        score, signals = smart_match(
            "Error: FileNotFoundError: /tmp/template.json not found during batch run",
            "FileNotFoundError: /tmp/template.json"
        )
        assert score >= 0.8

    def test_no_match(self):
        """Completely unrelated errors should not match."""
        score, signals = smart_match(
            "Connection refused to database server",
            "SyntaxError in JavaScript file line 42"
        )
        assert score < 0.5

    def test_regex_match(self):
        """Regex pattern should match."""
        score, signals = smart_match(
            "FileNotFoundError: /tmp/my-template.json",
            "FileNotFoundError: /tmp/template.json",
            pattern_regex=r"FileNotFoundError.*\/tmp\/.*\.json"
        )
        assert score >= 0.85
        signal_names = [s[0] for s in signals]
        assert "regex" in signal_names

    def test_error_class_match(self):
        """Same error class should produce some match."""
        score, signals = smart_match(
            "FileNotFoundError: /home/user/config.yaml",
            "No such file or directory: /etc/app.conf"
        )
        assert score >= 0.5
        signal_names = [s[0] for s in signals]
        assert "error_class" in signal_names

    def test_token_overlap(self):
        """Shared meaningful tokens should produce match."""
        score, signals = smart_match(
            "Failed to push git changes: remote ahead of local",
            "git push rejected: remote ahead"
        )
        assert score >= 0.5

    def test_ngram_similarity(self):
        """Similar strings should have n-gram overlap."""
        score, signals = smart_match(
            "ConnectionError: could not connect to api.example.com:443",
            "ConnectionError: could not connect to api.example.com:8080"
        )
        assert score >= 0.7

    def test_path_similarity(self):
        """Errors with similar file paths should match."""
        score, signals = smart_match(
            "Error reading /home/user/app/config/settings.json",
            "Failed to parse /home/user/app/config/database.json"
        )
        assert score >= 0.5

    def test_invalid_regex_handled(self):
        """Invalid regex should not crash."""
        score, signals = smart_match(
            "some error",
            "some pattern",
            pattern_regex="[invalid(regex"
        )
        # Should not raise, just skip regex signal
        assert isinstance(score, float)

    def test_multiple_signals_boost(self):
        """Multiple matching signals should boost the score."""
        # This error matches on substring, error_class, tokens, ngrams, and paths
        score, signals = smart_match(
            "FileNotFoundError: /tmp/compare-shell-template.json",
            "FileNotFoundError: /tmp/compare-shell-template.json"
        )
        assert score >= 0.9
        assert len(signals) >= 3  # Multiple signals should fire


class TestClassifyError:
    """Test error classification."""

    def test_file_not_found(self):
        classes = classify_error("FileNotFoundError: /tmp/foo.txt")
        assert "file_not_found" in classes

    def test_permission(self):
        classes = classify_error("Permission denied: /etc/shadow")
        assert "permission" in classes

    def test_connection(self):
        classes = classify_error("Connection refused at port 5432")
        assert "connection" in classes

    def test_timeout(self):
        classes = classify_error("Request timed out after 30s")
        assert "timeout" in classes

    def test_rate_limit(self):
        classes = classify_error("429 Too Many Requests")
        assert "rate_limit" in classes

    def test_auth(self):
        classes = classify_error("401 Unauthorized")
        assert "auth" in classes

    def test_multiple_classes(self):
        classes = classify_error("Connection refused: 401 Unauthorized timeout")
        assert len(classes) >= 2

    def test_unknown_error(self):
        classes = classify_error("Something weird happened")
        assert len(classes) == 0

    def test_import_error(self):
        classes = classify_error("ModuleNotFoundError: No module named 'pandas'")
        assert "import" in classes

    def test_json_parse(self):
        classes = classify_error("JSONDecodeError: Unexpected token at line 1")
        assert "json_parse" in classes


class TestNgramOverlap:
    """Test n-gram overlap calculation."""

    def test_identical_strings(self):
        score = ngram_overlap("hello world", "hello world")
        assert score == 1.0

    def test_completely_different(self):
        score = ngram_overlap("aaaaaa", "zzzzzz")
        assert score == 0.0

    def test_partial_overlap(self):
        score = ngram_overlap("hello world", "hello earth")
        assert 0.0 < score < 1.0

    def test_short_strings(self):
        score = ngram_overlap("ab", "ab")
        assert score == 0.0  # Too short for n=3

    def test_empty_string(self):
        score = ngram_overlap("", "hello")
        assert score == 0.0


class TestExtractPaths:
    """Test path extraction from error text."""

    def test_unix_path(self):
        paths = extract_paths("Error at /home/user/app/main.py line 42")
        assert any("/home/user/app/main.py" in p for p in paths)

    def test_quoted_path(self):
        paths = extract_paths("File '/tmp/config.json' not found")
        assert any("config.json" in p for p in paths)

    def test_no_paths(self):
        paths = extract_paths("Something went wrong")
        assert len(paths) == 0
