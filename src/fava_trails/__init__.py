"""FAVA Trails — Federated Agents Versioned Audit Trail."""

from __future__ import annotations

try:
    from importlib.metadata import PackageNotFoundError, version
except ImportError:  # pragma: no cover
    from importlib_metadata import PackageNotFoundError, version  # type: ignore

try:
    __version__ = version("fava-trails")
except PackageNotFoundError:  # pragma: no cover - source tree without install metadata
    __version__ = "0.6.1"
