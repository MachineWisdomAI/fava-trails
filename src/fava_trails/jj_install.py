"""Install and select a Jujutsu (JJ) binary for FAVA Trails.

Policy (issue #98):
- Supported minimum is JJ_MIN_VERSION (integration-tested).
- Reuse any installed JJ at or above the minimum; never silently downgrade.
- Never overwrite a user-managed executable outside the managed install path.
- When installation is needed, resolve the current official GitHub stable release
  unless an explicit version override is provided (CLI --version / JJ_VERSION).
- Validate downloads with official GitHub asset digests when available, install
  atomically, verify the resulting binary, and restore the prior binary on failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path

# Floor supported by FAVA Trails integration tests (see docs/jj-compatibility.md).
JJ_MIN_VERSION = "0.28.0"

# Managed install location — the only path installers will replace in-place.
DEFAULT_INSTALL_DIR = Path.home() / ".local" / "bin"
MANAGED_BINARY_NAME = "jj"

GITHUB_API_LATEST = "https://api.github.com/repos/jj-vcs/jj/releases/latest"
GITHUB_API_TAG = "https://api.github.com/repos/jj-vcs/jj/releases/tags/v{version}"
GITHUB_ASSET_URL = (
    "https://github.com/jj-vcs/jj/releases/download/v{version}/jj-v{version}-{suffix}.tar.gz"
)

_VERSION_RE = re.compile(r"\bjj\s+(\d+\.\d+\.\d+)\b", re.IGNORECASE)
_NETWORK_TIMEOUT_S = 30


class JjInstallError(Exception):
    """User-facing installer failure (message already actionable)."""


@total_ordering
@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, text: str) -> Version:
        parts = text.strip().lstrip("vV").split(".")
        if len(parts) < 3:
            raise ValueError(f"invalid version: {text!r}")
        try:
            return cls(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as e:
            raise ValueError(f"invalid version: {text!r}") from e

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)


@dataclass(frozen=True)
class ExistingJj:
    path: Path
    version: Version
    raw_version_line: str
    managed: bool


@dataclass(frozen=True)
class PlatformTarget:
    os_name: str
    machine: str
    suffix: str


@dataclass(frozen=True)
class ReleaseAsset:
    version: str
    url: str
    sha256: str | None
    source: str  # "explicit" | "latest" | "override-env"


@dataclass(frozen=True)
class SelectionResult:
    """Outcome of selecting or installing a JJ binary."""

    action: str  # reuse | install | refuse | error
    path: str | None
    version: str | None
    reason: str
    exit_code: int = 0


def managed_jj_path(install_dir: Path | None = None) -> Path:
    return (install_dir or DEFAULT_INSTALL_DIR) / MANAGED_BINARY_NAME


def parse_version_from_output(output: str) -> Version | None:
    match = _VERSION_RE.search(output or "")
    if not match:
        return None
    try:
        return Version.parse(match.group(1))
    except ValueError:
        return None


def is_compatible(version: Version, minimum: Version | None = None) -> bool:
    floor = minimum or Version.parse(JJ_MIN_VERSION)
    return version >= floor


def detect_platform(
    os_name: str | None = None,
    machine: str | None = None,
) -> PlatformTarget:
    os_name = (os_name or sys.platform).lower()
    machine = (machine or platform.machine()).lower()

    if os_name.startswith("win"):
        raise JjInstallError(
            "Windows detected. Install JJ with:\n"
            "  winget install Jujutsu.Jujutsu\n"
            "Or manually from: https://jj-vcs.github.io/jj/"
        )

    if os_name.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            suffix = "x86_64-unknown-linux-musl"
        elif machine in ("aarch64", "arm64"):
            suffix = "aarch64-unknown-linux-musl"
        else:
            raise JjInstallError(
                f"Unsupported Linux architecture: {machine}\n"
                "Install manually from: https://jj-vcs.github.io/jj/"
            )
        return PlatformTarget(os_name="linux", machine=machine, suffix=suffix)

    if os_name == "darwin":
        if machine in ("x86_64", "amd64"):
            suffix = "x86_64-apple-darwin"
        elif machine in ("arm64", "aarch64"):
            suffix = "aarch64-apple-darwin"
        else:
            raise JjInstallError(
                f"Unsupported macOS architecture: {machine}\n"
                "Install manually from: https://jj-vcs.github.io/jj/"
            )
        return PlatformTarget(os_name="darwin", machine=machine, suffix=suffix)

    raise JjInstallError(
        f"Unsupported OS: {os_name}\nInstall manually from: https://jj-vcs.github.io/jj/"
    )


def find_jj_candidates(install_dir: Path | None = None) -> list[Path]:
    """Return candidate jj paths in preference order (PATH first, then managed)."""
    seen: set[str] = set()
    out: list[Path] = []
    which = shutil.which("jj")
    if which:
        p = Path(which).resolve()
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    managed = managed_jj_path(install_dir)
    if managed.is_file():
        p = managed.resolve()
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def probe_jj(
    path: Path,
    *,
    timeout: float = 5.0,
    install_dir: Path | None = None,
) -> ExistingJj | None:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or result.stderr or "").strip().splitlines()
    raw = line[0] if line else ""
    version = parse_version_from_output(raw) or parse_version_from_output(result.stdout or "")
    if version is None:
        return None
    managed = _is_managed_path(path, install_dir=install_dir)
    return ExistingJj(path=path, version=version, raw_version_line=raw or f"jj {version}", managed=managed)


def _is_managed_path(path: Path, install_dir: Path | None = None) -> bool:
    try:
        return path.resolve() == managed_jj_path(install_dir).resolve()
    except OSError:
        return False


def discover_existing(install_dir: Path | None = None) -> ExistingJj | None:
    for candidate in find_jj_candidates(install_dir):
        probed = probe_jj(candidate, install_dir=install_dir)
        if probed is not None:
            return probed
    return None


def _http_get_json(url: str, *, timeout: float = _NETWORK_TIMEOUT_S) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "fava-trails-install-jj",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise JjInstallError(f"GitHub API request failed ({e.code}) for {url}: {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JjInstallError(f"Network error resolving JJ release ({url}): {e}") from e
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise JjInstallError(f"Invalid JSON from GitHub API ({url})") from e


def _http_download(url: str, dest: Path, *, timeout: float = _NETWORK_TIMEOUT_S) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "fava-trails-install-jj"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except urllib.error.HTTPError as e:
        raise JjInstallError(f"Download failed ({e.code}) for {url}: {e.reason}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JjInstallError(f"Download failed for {url}: {e}") from e


def resolve_release(
    explicit_version: str | None,
    *,
    platform_target: PlatformTarget,
    fetch_json=_http_get_json,
) -> ReleaseAsset:
    """Resolve which JJ release to install.

    explicit_version wins (CLI --version or JJ_VERSION). Otherwise query GitHub
    latest stable. Never freezes a permanent default patch version in code.
    """
    if explicit_version:
        version = explicit_version.lstrip("vV")
        # Validate shape early
        Version.parse(version)
        data = fetch_json(GITHUB_API_TAG.format(version=version))
        return _asset_from_release_payload(
            data,
            version=version,
            suffix=platform_target.suffix,
            source="explicit",
        )

    data = fetch_json(GITHUB_API_LATEST)
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    if not version:
        raise JjInstallError("GitHub latest release response missing tag_name")
    Version.parse(version)
    return _asset_from_release_payload(
        data,
        version=version,
        suffix=platform_target.suffix,
        source="latest",
    )


def _asset_from_release_payload(
    data: dict,
    *,
    version: str,
    suffix: str,
    source: str,
) -> ReleaseAsset:
    asset_name = f"jj-v{version}-{suffix}.tar.gz"
    sha256: str | None = None
    url = GITHUB_ASSET_URL.format(version=version, suffix=suffix)
    for asset in data.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") != asset_name:
            continue
        browser = asset.get("browser_download_url")
        if isinstance(browser, str) and browser:
            url = browser
        digest = asset.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            sha256 = digest.split(":", 1)[1].strip().lower()
        break
    return ReleaseAsset(version=version, url=url, sha256=sha256, source=source)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_jj_from_tarball(tarball: Path, dest_dir: Path) -> Path:
    """Safely extract the jj binary member into dest_dir/jj."""
    with tarfile.open(tarball, "r:gz") as tf:
        members = [m for m in tf.getmembers() if Path(m.name).name == "jj"]
        if not members:
            raise JjInstallError("jj binary not found in tarball")
        member = members[0]
        if not member.isfile():
            raise JjInstallError("jj entry in tarball is not a regular file")
        # Reject path traversal / absolute paths in member name
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise JjInstallError(f"refusing unsafe tarball member path: {member.name!r}")
        src_f = tf.extractfile(member)
        if src_f is None:
            raise JjInstallError("failed to read jj from tarball")
        extracted = dest_dir / "jj"
        with src_f, open(extracted, "wb") as dst_f:
            shutil.copyfileobj(src_f, dst_f)
    extracted.chmod(0o755)
    return extracted


def verify_executable_version(path: Path, expected: Version | None = None) -> Version:
    probed = probe_jj(path)
    if probed is None:
        raise JjInstallError(f"installed binary at {path} failed --version probe")
    if expected is not None and probed.version != expected:
        raise JjInstallError(
            f"version mismatch after install: expected {expected}, got {probed.version}"
        )
    return probed.version


def atomic_install(
    extracted: Path,
    dest: Path,
    *,
    expected_version: Version,
) -> ExistingJj:
    """Install extracted binary at dest atomically; restore prior binary on failure."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    staged = dest.with_name(dest.name + ".fava-new")
    try:
        # Stage next to dest so os.replace is same-filesystem atomic.
        if staged.exists():
            staged.unlink()
        shutil.copy2(extracted, staged)
        staged.chmod(0o755)
        verify_executable_version(staged, expected_version)

        if dest.exists() or dest.is_symlink():
            backup = dest.with_name(dest.name + ".fava-prev")
            if backup.exists():
                backup.unlink()
            os.replace(dest, backup)

        os.replace(staged, dest)
        final = verify_executable_version(dest, expected_version)
        if backup is not None and backup.exists():
            backup.unlink()
        return ExistingJj(
            path=dest,
            version=final,
            raw_version_line=f"jj {final}",
            managed=True,
        )
    except Exception:
        # Best-effort restore
        if backup is not None and backup.exists() and not dest.exists():
            try:
                os.replace(backup, dest)
            except OSError:
                # Best-effort restore only; the original install failure is re-raised.
                pass
        if staged.exists():
            try:
                staged.unlink()
            except OSError:
                # Staged leftover cleanup is best-effort; original failure is re-raised.
                pass
        raise


def path_hint() -> str:
    shell = os.environ.get("SHELL", "")
    shell_rc = ".zshrc" if "zsh" in shell or sys.platform == "darwin" else ".bashrc"
    return (
        f"Warning: {DEFAULT_INSTALL_DIR} is not in your PATH.\n"
        "Add it with:\n"
        f'  echo \'export PATH="$HOME/.local/bin:$PATH"\' >> ~/{shell_rc} && source ~/{shell_rc}'
    )


def select_or_install(
    *,
    explicit_version: str | None = None,
    install_dir: Path | None = None,
    force_install: bool = False,
    fetch_json=_http_get_json,
    download=_http_download,
    os_name: str | None = None,
    machine: str | None = None,
    which_jj: str | None | object = ...,  # test seam; ellipsis = live discovery
) -> SelectionResult:
    """Main entry: reuse compatible JJ or install current stable / override.

    Returns SelectionResult with action, path, version, reason, exit_code.
    Does not print; callers format user-facing messages.
    """
    install_dir = install_dir or DEFAULT_INSTALL_DIR
    min_version = Version.parse(JJ_MIN_VERSION)

    try:
        platform_target = detect_platform(os_name=os_name, machine=machine)
    except JjInstallError as e:
        return SelectionResult(action="error", path=None, version=None, reason=str(e), exit_code=1)

    # Discover existing
    existing: ExistingJj | None = None
    if which_jj is ...:
        existing = discover_existing(install_dir)
    elif which_jj is None:
        existing = None
    else:
        existing = probe_jj(Path(str(which_jj)), install_dir=install_dir)

    # Reuse rules
    if existing is not None and not force_install:
        if explicit_version:
            want = Version.parse(explicit_version.lstrip("vV"))
            if existing.version == want:
                return SelectionResult(
                    action="reuse",
                    path=str(existing.path),
                    version=str(existing.version),
                    reason=(
                        f"exact match for requested {want} at {existing.path} "
                        f"({'managed' if existing.managed else 'user-managed'})"
                    ),
                    exit_code=0,
                )
            if not existing.managed:
                return SelectionResult(
                    action="refuse",
                    path=str(existing.path),
                    version=str(existing.version),
                    reason=(
                        f"user-managed JJ {existing.version} at {existing.path} differs from "
                        f"requested {want}; refusing to overwrite. Uninstall/move it, or put "
                        f"{managed_jj_path(install_dir)} first on PATH after installing there."
                    ),
                    exit_code=1,
                )
            # Managed path, wrong version → install override below
        elif is_compatible(existing.version, min_version):
            return SelectionResult(
                action="reuse",
                path=str(existing.path),
                version=str(existing.version),
                reason=(
                    f"compatible installed JJ {existing.version} (>= {min_version}) at "
                    f"{existing.path}; not downgrading or replacing"
                ),
                exit_code=0,
            )
        else:
            # Incompatible older
            if not existing.managed:
                return SelectionResult(
                    action="refuse",
                    path=str(existing.path),
                    version=str(existing.version),
                    reason=(
                        f"user-managed JJ {existing.version} at {existing.path} is below "
                        f"minimum {min_version}; refusing to overwrite. Upgrade via your "
                        f"package manager, or remove it from PATH and re-run install-jj."
                    ),
                    exit_code=1,
                )
            # Managed but too old → upgrade path below

    # Resolve target release (needs network unless we already returned)
    try:
        release = resolve_release(
            explicit_version,
            platform_target=platform_target,
            fetch_json=fetch_json,
        )
    except JjInstallError as e:
        # Offline / API failure: if we still have something usable, say so clearly
        if existing is not None and is_compatible(existing.version, min_version) and not explicit_version:
            return SelectionResult(
                action="reuse",
                path=str(existing.path),
                version=str(existing.version),
                reason=(
                    f"release resolution failed ({e}); reusing compatible installed "
                    f"JJ {existing.version} at {existing.path}"
                ),
                exit_code=0,
            )
        return SelectionResult(
            action="error",
            path=str(existing.path) if existing else None,
            version=str(existing.version) if existing else None,
            reason=(
                f"could not resolve JJ release and no compatible install available: {e}"
            ),
            exit_code=1,
        )

    expected = Version.parse(release.version)
    dest = managed_jj_path(install_dir)

    # If existing managed and already exact target, reuse
    if existing is not None and existing.managed and existing.version == expected:
        return SelectionResult(
            action="reuse",
            path=str(existing.path),
            version=str(existing.version),
            reason=f"managed JJ already at target {expected}",
            exit_code=0,
        )

    # Download + install
    try:
        with tempfile.TemporaryDirectory(prefix="fava-jj-") as tmp:
            tmp_path = Path(tmp)
            tarball = tmp_path / "jj.tar.gz"
            download(release.url, tarball)
            if release.sha256:
                actual = _sha256_file(tarball)
                if actual != release.sha256:
                    raise JjInstallError(
                        f"SHA-256 mismatch for {release.url}: expected {release.sha256}, got {actual}"
                    )
            extracted = extract_jj_from_tarball(tarball, tmp_path)
            installed = atomic_install(extracted, dest, expected_version=expected)
    except JjInstallError as e:
        return SelectionResult(
            action="error",
            path=str(existing.path) if existing else None,
            version=str(existing.version) if existing else None,
            reason=f"install failed (prior executable preserved if present): {e}",
            exit_code=1,
        )
    except Exception as e:
        return SelectionResult(
            action="error",
            path=str(existing.path) if existing else None,
            version=str(existing.version) if existing else None,
            reason=f"install failed (prior executable preserved if present): {e}",
            exit_code=1,
        )

    reason = (
        f"installed JJ {installed.version} to {installed.path} "
        f"(resolved via {release.source}"
        f"{', sha256 verified' if release.sha256 else ', no official digest for this tag'}"
        f")"
    )
    return SelectionResult(
        action="install",
        path=str(installed.path),
        version=str(installed.version),
        reason=reason,
        exit_code=0,
    )


def format_selection_report(result: SelectionResult) -> str:
    parts = [
        f"action:  {result.action}",
        f"path:    {result.path or '(none)'}",
        f"version: {result.version or '(none)'}",
        f"reason:  {result.reason}",
    ]
    return "\n".join(parts)
