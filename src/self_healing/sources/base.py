"""
Abstract base class for failure sources.

All source plugins must subclass FailureSource and implement scan().
"""

from abc import ABC, abstractmethod


class FailureSource(ABC):
    """
    Base class for failure source plugins.

    Each source scans a specific system for failures and returns
    a list of failure dicts with a consistent schema.
    """

    name: str = "base"

    @abstractmethod
    def scan(self, hours: int = 6) -> list[dict]:
        """
        Scan for failures within the given time window.

        Returns list of failure dicts, each with:
            source: str    — source identifier (e.g., "cron", "logfile")
            id: str        — unique identifier for this failure
            name: str      — human-readable label
            error: str     — error message or description
            timestamp: str — ISO 8601 timestamp
            severity: str  — "critical", "warning", or "info"
        """
        raise NotImplementedError

    @classmethod
    def from_config(cls, config: dict) -> "FailureSource":
        """Create an instance from a config dict."""
        return cls()

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"
