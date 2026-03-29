"""Tests for the smart matching engine."""

from self_healing.healer import smart_match, classify_error, ngram_overlap, extract_paths


class TestSmartMatch:
    """Test the multi-signal smart matching engine."""

    def test_exact_substring_match(self):
        score, signals = smart_match(
            "FileNotFoundError: /tmp/template.json not found",
            "FileNotFoundError: /tmp/template.json not found"
        )
        assert score >= 0.9
        signal_names = [s[0] for s in signals]
        assert "substring" in signal_names

    def test_substring_contained(self):
        score, signals = smart_match(
            "Error: FileNotFoundError: /tmp/template.json not found during batch run",
            "FileNotFoundError: /tmp/template.json"
        )
        assert score >= 0.8

    def test_no_match(self):
        score, signals = smart_match(
            "Connection refused to database server",
            "SyntaxError in JavaScript file line 42"
        )
        assert score < 0.5

    def test_regex_match(self):
        score, signals = smart_match(
            "FileNotFoundError: /tmp/my-template.json",
            "FileNotFoundError: /tmp/template.json",
            pattern_regex=r"FileNotFoundError.*\/tmp\/.*\.json"
        )
        assert score >= 0.85
        signal_names = [s[0] for s in signals]
        assert "regex" in signal_names

    def test_error_class_match(self):
        score, signals = smart_match(
            "FileNotFoundError: /home/user/config.yaml",
            "No such file or directory: /etc/app.conf"
        )
        assert score >= 0.5
        signal_names = [s[0] for s in signals]
        assert "error_class" in signal_names

    def test_token_overlap(self):
        score, signals = smart_match(
            "Failed to push git changes: remote ahead of local",
            "git push rejected: remote ahead"
        )
        assert score >= 0.5

    def test_ngram_similarity(self):
        score, signals = smart_match(
            "ConnectionError: could not connect to api.example.com:443",
            "ConnectionError: could not connect to api.example.com:8080"
        )
        assert score >= 0.7

    def test_path_similarity(self):
        score, signals = smart_match(
            "Error reading /home/user/app/config/settings.json",
            "Failed to parse /home/user/app/config/database.json"
        )
        assert score >= 0.5

    def test_invalid_regex_handled(self):
        score, signals = smart_match(
            "some error",
            "some pattern",
            pattern_regex="[invalid(regex"
        )
        assert isinstance(score, float)

    def test_multiple_signals_boost(self):
        score, signals = smart_match(
            "FileNotFoundError: /tmp/compare-shell-template.json",
            "FileNotFoundError: /tmp/compare-shell-template.json"
        )
        assert score >= 0.9
        assert len(signals) >= 3


class TestClassifyError:
    """Test error classification."""

    def test_file_not_found(self):
        assert "file_not_found" in classify_error("FileNotFoundError: /tmp/foo.txt")

    def test_permission(self):
        assert "permission" in classify_error("Permission denied: /etc/shadow")

    def test_connection(self):
        assert "connection" in classify_error("Connection refused at port 5432")

    def test_timeout(self):
        assert "timeout" in classify_error("Request timed out after 30s")

    def test_rate_limit(self):
        assert "rate_limit" in classify_error("429 Too Many Requests")

    def test_auth(self):
        assert "auth" in classify_error("401 Unauthorized")

    def test_multiple_classes(self):
        classes = classify_error("Connection refused: 401 Unauthorized timeout")
        assert len(classes) >= 2

    def test_unknown_error(self):
        assert len(classify_error("Something weird happened")) == 0

    def test_import_error(self):
        assert "import" in classify_error("ModuleNotFoundError: No module named 'pandas'")

    def test_json_parse(self):
        assert "json_parse" in classify_error("JSONDecodeError: Unexpected token at line 1")


class TestNgramOverlap:
    """Test n-gram overlap calculation."""

    def test_identical_strings(self):
        assert ngram_overlap("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert ngram_overlap("aaaaaa", "zzzzzz") == 0.0

    def test_partial_overlap(self):
        score = ngram_overlap("hello world", "hello earth")
        assert 0.0 < score < 1.0

    def test_short_strings(self):
        assert ngram_overlap("ab", "ab") == 0.0

    def test_empty_string(self):
        assert ngram_overlap("", "hello") == 0.0


class TestExtractPaths:
    """Test path extraction from error text."""

    def test_unix_path(self):
        paths = extract_paths("Error at /home/user/app/main.py line 42")
        assert any("/home/user/app/main.py" in p for p in paths)

    def test_quoted_path(self):
        paths = extract_paths("File '/tmp/config.json' not found")
        assert any("config.json" in p for p in paths)

    def test_no_paths(self):
        assert len(extract_paths("Something went wrong")) == 0
