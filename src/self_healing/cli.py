"""
Unified CLI for self-healing-agents.

Usage:
    self-heal scan [--hours N] [--source NAME] [--config PATH] [--json]
    self-heal check "<error message>"
    self-heal log --error "..." --cause "..." --fix "..." --fix-type heal
    self-heal list
    self-heal stats
    self-heal risk "<description>"
    self-heal version
"""

import argparse
import sys

from . import __version__


def cmd_scan(args):
    """Run the failure scanner."""
    from .scanner import run_scan
    run_scan(
        hours=args.hours,
        output_json=args.json,
        source_names=args.source or [],
        config_path=args.config,
    )


def cmd_check(args):
    """Check for a known fix."""
    from .healer import cmd_check as _check
    _check(args.error)


def cmd_log(args):
    """Log a new known fix."""
    from .healer import cmd_log as _log
    files_changed = args.files_changed.split(",") if args.files_changed else None
    _log(
        error=args.error,
        cause=args.cause,
        fix=args.fix,
        fix_type=args.fix_type,
        files_changed=files_changed,
        commit=args.commit,
    )


def cmd_list(args):
    """List all known fixes."""
    from .healer import cmd_list as _list
    _list()


def cmd_stats(args):
    """Show statistics."""
    from .healer import cmd_stats as _stats
    _stats()


def cmd_risk(args):
    """Score risk of a fix."""
    from .healer import cmd_risk as _risk
    _risk(args.description)


def cmd_notified(args):
    """Check if a heal was already notified."""
    from .healer import cmd_notified as _notified
    _notified(args.error)


def cmd_mark_notified(args):
    """Mark a heal as notified."""
    from .healer import mark_notified as _mark
    _mark(args.fix_id, args.error, args.fix or "")
    import json
    print(json.dumps({"marked": True, "error": args.error[:100]}))


def cmd_clear_notified(args):
    """Clear notification records."""
    from .healer import cmd_clear_notified as _clear
    _clear(args.fix_id)


def cmd_version(args):
    """Print version."""
    print(f"self-healing-agents v{__version__}")


def build_parser():
    """Build the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="self-heal",
        description="Self-healing agents — autonomous error detection, diagnosis, and repair.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan
    p_scan = subparsers.add_parser("scan", help="Scan for failures across sources")
    p_scan.add_argument("--hours", type=int, default=6, help="Look back N hours (default: 6)")
    p_scan.add_argument("--source", action="append", help="Scan only this source (repeatable)")
    p_scan.add_argument("--config", help="Path to config file (YAML or JSON)")
    p_scan.add_argument("--json", action="store_true", help="Output raw JSON")
    p_scan.set_defaults(func=cmd_scan)

    # check
    p_check = subparsers.add_parser("check", help="Check for a known fix for an error")
    p_check.add_argument("error", help="Error message to look up")
    p_check.set_defaults(func=cmd_check)

    # log
    p_log = subparsers.add_parser("log", help="Log a new known fix")
    p_log.add_argument("--error", required=True, help="Error message pattern")
    p_log.add_argument("--cause", required=True, help="Root cause description")
    p_log.add_argument("--fix", required=True, help="Fix description")
    p_log.add_argument("--fix-type", default="heal", choices=["heal", "patch", "retry"],
                       help="Fix type (default: heal)")
    p_log.add_argument("--files-changed", help="Comma-separated list of changed files")
    p_log.add_argument("--commit", help="Git commit hash")
    p_log.set_defaults(func=cmd_log)

    # list
    p_list = subparsers.add_parser("list", help="List all known fixes")
    p_list.set_defaults(func=cmd_list)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show self-healing statistics")
    p_stats.set_defaults(func=cmd_stats)

    # risk
    p_risk = subparsers.add_parser("risk", help="Score the risk of a fix or system change")
    p_risk.add_argument("description", help="Description of the fix or change")
    p_risk.set_defaults(func=cmd_risk)

    # notified
    p_notified = subparsers.add_parser("notified", help="Check if a heal was already notified")
    p_notified.add_argument("error", help="Error message to check")
    p_notified.set_defaults(func=cmd_notified)

    # mark-notified
    p_mark = subparsers.add_parser("mark-notified", help="Mark a heal as notified (suppress future alerts)")
    p_mark.add_argument("error", help="Error message that was healed")
    p_mark.add_argument("--fix-id", default=None, help="Known-fix ID")
    p_mark.add_argument("--fix", default=None, help="Description of the fix applied")
    p_mark.set_defaults(func=cmd_mark_notified)

    # clear-notified
    p_clear = subparsers.add_parser("clear-notified", help="Clear notification records")
    p_clear.add_argument("fix_id", nargs="?", default=None, help="Specific fix ID to clear (omit for all)")
    p_clear.set_defaults(func=cmd_clear_notified)

    # version
    p_version = subparsers.add_parser("version", help="Show version")
    p_version.set_defaults(func=cmd_version)

    return parser


def main(argv=None):
    """Main entry point for the self-heal CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
