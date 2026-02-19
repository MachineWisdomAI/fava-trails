"""Test fixtures for FAVA Trail."""

import os
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

# Skip all tests if jj is not installed
jj_bin = shutil.which("jj") or str(Path.home() / ".local" / "bin" / "jj")
if not Path(jj_bin).exists():
    pytest.skip("jj binary not found — install via scripts/install-jj.sh", allow_module_level=True)


@pytest.fixture
def tmp_fava_home(tmp_path):
    """Create a temporary FAVA_TRAIL_HOME directory."""
    home = tmp_path / "fava-trail"
    home.mkdir()
    (home / "trails").mkdir()
    os.environ["FAVA_TRAIL_HOME"] = str(home)
    yield home
    os.environ.pop("FAVA_TRAIL_HOME", None)


@pytest_asyncio.fixture
async def trail_manager(tmp_fava_home):
    """Create and initialize a TrailManager with a test trail."""
    from fava_trail.trail import TrailManager

    manager = TrailManager("test")
    await manager.init()
    return manager


@pytest_asyncio.fixture
async def jj_backend(tmp_fava_home):
    """Create a JjBackend with an initialized trail repo."""
    from fava_trail.vcs.jj_backend import JjBackend

    trail_path = tmp_fava_home / "trails" / "test-jj"
    trail_path.mkdir(parents=True)
    backend = JjBackend(trail_path)
    await backend.init_trail()
    return backend
