"""
Source plugin registry for self-healing failure scanning.

Built-in sources: openclaw, logfile, jsonl.
Custom sources can be registered via register_source().
"""

from .base import FailureSource

# Registry of available source classes
_REGISTRY: dict[str, type] = {}


def register_source(name: str, cls: type):
    """Register a source class by name."""
    if not issubclass(cls, FailureSource):
        raise TypeError(f"{cls.__name__} must be a subclass of FailureSource")
    _REGISTRY[name] = cls


def get_source(name: str, config: dict = None) -> FailureSource:
    """Get a source instance by name, optionally configured from a dict."""
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise KeyError(f"Unknown source '{name}'. Available: {available}")
    cls = _REGISTRY[name]
    if config:
        return cls.from_config(config)
    return cls()


def list_sources() -> list[str]:
    """Return names of all registered sources."""
    return sorted(_REGISTRY.keys())


def get_all_sources(config: dict = None) -> list[FailureSource]:
    """Get instances of all enabled sources from config, or all registered sources."""
    sources = []
    if config and "sources" in config:
        for name, src_config in config["sources"].items():
            if not src_config.get("enabled", True):
                continue
            if name in _REGISTRY:
                sources.append(get_source(name, src_config))
    else:
        # No config — return all registered sources with defaults
        for name, cls in _REGISTRY.items():
            sources.append(cls())
    return sources


# Auto-register built-in sources
def _register_builtins():
    from .openclaw import OpenClawSource
    from .logfile import LogFileSource
    from .jsonl import JSONLSource
    register_source("openclaw", OpenClawSource)
    register_source("logfile", LogFileSource)
    register_source("jsonl", JSONLSource)


_register_builtins()
