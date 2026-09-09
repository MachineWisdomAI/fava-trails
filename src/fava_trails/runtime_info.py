"""Loaded runtime identity: product version, provenance, and MCP SDK version."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Any


def product_version() -> str:
    """Return the installed FAVA Trails product version."""
    try:
        return importlib.metadata.version("fava-trails")
    except importlib.metadata.PackageNotFoundError:
        from fava_trails import __version__

        return __version__


def mcp_sdk_version() -> str:
    """Return the installed MCP Python SDK distribution version.

    This is independent of the FAVA product version advertised in handshake
    ``serverInfo.version``. Clients that surface a single "server version" may
    be showing either value depending on which metadata field they read.
    """
    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _module_path() -> Path:
    import fava_trails

    return Path(fava_trails.__file__).resolve()


def _source_kind(module_path: Path) -> str:
    parts = module_path.parts
    if "site-packages" in parts:
        return "installed"
    if "src" in parts:
        # Local checkout, worktree, or editable install resolved into the tree.
        return "editable"
    return "unknown"


def runtime_report() -> dict[str, Any]:
    """Describe the actually loaded runtime without credentials or secrets."""
    from fava_trails import __version__ as module_version

    module_path = _module_path()
    package_version = product_version()
    return {
        "product_name": "fava-trails",
        "package_version": package_version,
        "module_version": module_version,
        "module_path": str(module_path),
        "source_kind": _source_kind(module_path),
        "mcp_sdk_version": mcp_sdk_version(),
        "handshake_product_version": package_version,
    }


def format_runtime_report(report: dict[str, Any] | None = None) -> str:
    """Human-readable multi-line report for CLI / doctor output."""
    data = report or runtime_report()
    lines = [
        f"FAVA Trails product: {data['product_name']}",
        f"Package version:    {data['package_version']}",
        f"Module version:     {data['module_version']}",
        f"Module path:        {data['module_path']}",
        f"Source:             {data['source_kind']}",
        f"MCP SDK version:    {data['mcp_sdk_version']}",
        f"Handshake product version (serverInfo.version): {data['handshake_product_version']}",
    ]
    return "\n".join(lines) + "\n"
