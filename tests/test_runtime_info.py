"""Runtime version and provenance reporting (issue #99)."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from fava_trails import __version__ as module_version
from fava_trails.runtime_info import format_runtime_report, runtime_report


def test_runtime_report_separates_product_and_mcp_sdk_versions():
    report = runtime_report()
    package_version = importlib.metadata.version("fava-trails")
    mcp_version = importlib.metadata.version("mcp")

    assert report["product_name"] == "fava-trails"
    assert report["package_version"] == package_version
    assert report["module_version"] == module_version
    assert report["package_version"] == report["module_version"]
    assert report["mcp_sdk_version"] == mcp_version
    assert report["mcp_sdk_version"] != report["package_version"]
    assert Path(report["module_path"]).name == "__init__.py"
    assert "fava_trails" in report["module_path"]
    assert report["source_kind"] in {"editable", "installed", "unknown"}
    # Never leak credentials or data-repo secrets in the report payload.
    blob = format_runtime_report(report)
    assert "OPENROUTER" not in blob
    assert "api_key" not in blob.lower()
    assert "sk-" not in blob


def test_format_runtime_report_is_stable_and_human_readable():
    text = format_runtime_report(runtime_report())
    assert "FAVA Trails product:" in text
    assert "Package version:" in text
    assert "Module version:" in text
    assert "Module path:" in text
    assert "Source:" in text
    assert "MCP SDK version:" in text
    assert "serverInfo.version" in text or "Handshake product version" in text
