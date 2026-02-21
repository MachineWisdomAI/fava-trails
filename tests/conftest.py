"""Test fixtures for FAVA Trail."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

# Skip all tests if jj is not installed
jj_bin = shutil.which("jj") or str(Path.home() / ".local" / "bin" / "jj")
if not Path(jj_bin).exists():
    pytest.skip("jj binary not found — install via scripts/install-jj.sh", allow_module_level=True)


@pytest.fixture
def tmp_fava_home(tmp_path):
    """Create a temporary FAVA_TRAIL_DATA_REPO with monorepo initialized at root."""
    home = tmp_path / "fava-trail-data"
    home.mkdir()
    (home / "trails").mkdir()
    os.environ["FAVA_TRAIL_DATA_REPO"] = str(home)
    # Init monorepo at root (not per-trail)
    subprocess.run([jj_bin, "git", "init", "--colocate"], cwd=str(home), check=True)
    subprocess.run(
        [jj_bin, "config", "set", "--repo", "user.name", "FAVA Trail Test"],
        cwd=str(home), check=True,
    )
    subprocess.run(
        [jj_bin, "config", "set", "--repo", "user.email", "test@fava-trail.dev"],
        cwd=str(home), check=True,
    )
    yield home
    os.environ.pop("FAVA_TRAIL_DATA_REPO", None)


@pytest_asyncio.fixture
async def jj_backend(tmp_fava_home):
    """Create a JjBackend with monorepo at root, trail as subdirectory."""
    from fava_trail.vcs.jj_backend import JjBackend

    trail_path = tmp_fava_home / "trails" / "test-jj"
    trail_path.mkdir(parents=True)
    backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
    await backend.init_trail()  # Creates dirs only, no repo init
    return backend


@pytest_asyncio.fixture
async def trail_manager(tmp_fava_home):
    """Create and initialize a TrailManager with a test trail."""
    from fava_trail.trail import TrailManager
    from fava_trail.vcs.jj_backend import JjBackend

    trail_path = tmp_fava_home / "trails" / "test"
    backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
    manager = TrailManager("test", vcs=backend)
    await manager.init()
    return manager


@pytest_asyncio.fixture
async def nested_trail_managers(tmp_fava_home):
    """Create multiple nested TrailManagers for hierarchical scoping tests.

    Returns dict with keys: 'company', 'team', 'project', 'epic'
    mapped to TrailManagers for mw, mw/eng, mw/eng/fava-trail, mw/eng/fava-trail/auth-epic.
    """
    from fava_trail.trail import TrailManager
    from fava_trail.vcs.jj_backend import JjBackend

    managers = {}
    for name, key in [
        ("mw", "company"),
        ("mw/eng", "team"),
        ("mw/eng/fava-trail", "project"),
        ("mw/eng/fava-trail/auth-epic", "epic"),
    ]:
        trail_path = tmp_fava_home / "trails" / name
        backend = JjBackend(repo_root=tmp_fava_home, trail_path=trail_path)
        manager = TrailManager(name, vcs=backend)
        await manager.init()
        managers[key] = manager

    return managers
