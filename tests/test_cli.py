"""Tests for the unified CLI."""

import pytest
from self_healing.cli import build_parser, main
from self_healing import __version__


class TestCLIParser:
    """Test that the CLI parses args correctly for each subcommand."""

    def setup_method(self):
        self.parser = build_parser()

    def test_scan_defaults(self):
        args = self.parser.parse_args(["scan"])
        assert args.command == "scan"
        assert args.hours == 6
        assert args.json is False
        assert args.source is None
        assert args.config is None

    def test_scan_with_options(self):
        args = self.parser.parse_args(["scan", "--hours", "24", "--json", "--source", "logfile", "--config", "test.yaml"])
        assert args.hours == 24
        assert args.json is True
        assert args.source == ["logfile"]
        assert args.config == "test.yaml"

    def test_scan_multiple_sources(self):
        args = self.parser.parse_args(["scan", "--source", "logfile", "--source", "jsonl"])
        assert args.source == ["logfile", "jsonl"]

    def test_check(self):
        args = self.parser.parse_args(["check", "FileNotFoundError: /tmp/foo.json"])
        assert args.command == "check"
        assert args.error == "FileNotFoundError: /tmp/foo.json"

    def test_log(self):
        args = self.parser.parse_args([
            "log",
            "--error", "some error",
            "--cause", "some cause",
            "--fix", "some fix",
            "--fix-type", "patch",
            "--files-changed", "a.py,b.py",
            "--commit", "abc123",
        ])
        assert args.command == "log"
        assert args.error == "some error"
        assert args.cause == "some cause"
        assert args.fix == "some fix"
        assert args.fix_type == "patch"
        assert args.files_changed == "a.py,b.py"
        assert args.commit == "abc123"

    def test_log_defaults(self):
        args = self.parser.parse_args(["log", "--error", "e", "--cause", "c", "--fix", "f"])
        assert args.fix_type == "heal"
        assert args.files_changed is None
        assert args.commit is None

    def test_list(self):
        args = self.parser.parse_args(["list"])
        assert args.command == "list"

    def test_stats(self):
        args = self.parser.parse_args(["stats"])
        assert args.command == "stats"

    def test_risk(self):
        args = self.parser.parse_args(["risk", "deploy to production"])
        assert args.command == "risk"
        assert args.description == "deploy to production"

    def test_version(self):
        args = self.parser.parse_args(["version"])
        assert args.command == "version"

    def test_no_command_prints_help(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 1


class TestCLIVersion:
    """Test the version command."""

    def test_version_output(self, capsys):
        main(["version"])
        captured = capsys.readouterr()
        assert __version__ in captured.out
        assert "self-healing-agents" in captured.out


class TestCLIScanHelp:
    """Test that scan --help works."""

    def test_scan_help(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["scan", "--help"])
        assert exc_info.value.code == 0
