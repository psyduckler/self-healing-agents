"""Tests for notification deduplication."""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Override workspace before importing healer
_tmpdir = tempfile.mkdtemp()
os.environ["OPENCLAW_WORKSPACE"] = _tmpdir

from self_healing.healer import (
    was_already_notified,
    mark_notified,
    clear_notification,
    clear_all_notifications,
    load_notifications,
    NOTIFICATIONS_PATH,
)


@pytest.fixture(autouse=True)
def clean_notifications():
    """Ensure clean state for each test."""
    if NOTIFICATIONS_PATH.exists():
        NOTIFICATIONS_PATH.unlink()
    yield
    if NOTIFICATIONS_PATH.exists():
        NOTIFICATIONS_PATH.unlink()


def test_not_notified_initially():
    assert was_already_notified(None, "FileNotFoundError: /tmp/foo.json") is False


def test_mark_and_check():
    mark_notified("fix-123", "FileNotFoundError: /tmp/foo.json", "Moved to permanent path")
    assert was_already_notified("fix-123", "FileNotFoundError: /tmp/foo.json") is True


def test_different_error_not_notified():
    mark_notified("fix-123", "FileNotFoundError: /tmp/foo.json", "Moved file")
    assert was_already_notified(None, "ConnectionRefusedError: port 3000") is False


def test_clear_specific():
    mark_notified("fix-abc", "TimeoutError: API call", "Increased timeout")
    assert was_already_notified("fix-abc", "TimeoutError: API call") is True
    clear_notification(fix_id="fix-abc")
    assert was_already_notified("fix-abc", "TimeoutError: API call") is False


def test_clear_all():
    mark_notified("fix-1", "Error A", "Fix A")
    mark_notified("fix-2", "Error B", "Fix B")
    notifs = load_notifications()
    assert len(notifs) == 2
    clear_all_notifications()
    notifs = load_notifications()
    assert len(notifs) == 0


def test_mark_notified_stores_metadata():
    mark_notified("fix-meta", "SomeError: details", "Applied workaround")
    notifs = load_notifications()
    entry = notifs["fix-meta"]
    assert entry["error"] == "SomeError: details"
    assert entry["fix"] == "Applied workaround"
    assert "notifiedAt" in entry


def test_notified_without_fix_id_uses_error_key():
    """When no fix_id, error text itself is the key."""
    mark_notified(None, "FileNotFoundError: /tmp/template.json", "Recreated file")
    assert was_already_notified(None, "FileNotFoundError: /tmp/template.json") is True
    # Different error text = not notified
    assert was_already_notified(None, "FileNotFoundError: /tmp/other.json") is False
