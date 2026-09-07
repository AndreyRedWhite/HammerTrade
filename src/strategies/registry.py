"""Simple strategy registry — maps strategy name → class."""

from __future__ import annotations

_REGISTRY: dict[str, type] = {}


def register(cls):
    """Class decorator: registers strategy class by its .name attribute."""
    _REGISTRY[cls.name] = cls
    return cls


def get(name: str):
    """Return strategy class by name, raises KeyError if not found."""
    if name not in _REGISTRY:
        raise KeyError(f"Strategy '{name}' not registered. Available: {list_strategies()}")
    return _REGISTRY[name]


def list_strategies() -> list[str]:
    """Return list of registered strategy names."""
    return list(_REGISTRY.keys())
