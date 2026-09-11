# Runtime versions, identity, and upgrade behavior

FAVA Trails 0.6.1 fixes (governed recall isolation from #72 / #93 and MCP
registration compatibility from #83 / #94) are **merged on `main` but not yet
published** to PyPI or a GitHub Release. Live `pip install fava-trails` still
resolves **0.6.0** until an authorized tag-driven release runs. Treat anything
newer on `main` as a release candidate until publication is verified.

## Report the loaded runtime

MCP client configs often keep a local checkout, vendor pin, or `uv run
--directory …` selector active after a package upgrade. Those selectors do not
automatically follow PyPI. Ask the process that is actually running:

```bash
fava-trails version
# or
fava-trails doctor   # prints the same runtime block first
```

Example (values vary by install):

```text
FAVA Trails product: fava-trails
Package version:    0.6.1
Module version:     0.6.1
Module path:        /…/site-packages/fava_trails/__init__.py
Source:             installed
MCP SDK version:    2.2.0
Handshake product version (serverInfo.version): 0.6.1
```

| Field | Meaning |
| --- | --- |
| Package / module version | FAVA product version (`importlib.metadata` and `fava_trails.__version__`) |
| Module path | Which tree the interpreter imported — use this to spot a stale checkout |
| Source | `installed` (site-packages wheel) vs `editable` (local `src/` tree) |
| MCP SDK version | Python `mcp` distribution version — **not** the FAVA product version |
| Handshake product version | Value sent as MCP `serverInfo.version` on `initialize` |

`fava-trails version` never prints credentials, API keys, or data-repo secrets.

### Handshake vs SDK version

On stdio `initialize`, FAVA advertises:

- `serverInfo.name`: `fava-trails`
- `serverInfo.version`: **FAVA product version** (for example `0.6.1`)

The MCP Python SDK has its own distribution version (for example `2.2.0`). A
client UI that shows a single "server version" may be reading either product
metadata or its own SDK/client field. Do not assume every version string shares
one meaning. Use `fava-trails version` for the loaded product and SDK pair.

### Direct stdio probe vs native client registration

These are two different evidence paths and must not be conflated:

| Path | What it proves | Automated coverage |
| --- | --- | --- |
| **Direct stdio probe** | The installed `fava-trails-server` binary speaks MCP over stdio when launched by absolute path | `tests/test_mcp_protocol.py::test_installed_stdio_initialize_list_and_call` |
| **Native client registration** | A real native client (`npx @modelcontextprotocol/inspector` CLI) loads a Claude-shaped `mcpServers` config, resolves `command`/`env`, spawns the server, and completes `initialize` + `tools/list` + `tools/call`. Pytest does not parse or launch the registration. | `tests/test_mcp_protocol.py::test_native_client_registration_loads_and_initializes` |

Installing a wheel does not update a running client until the registration is
restarted. `tests/test_packaged_mcp.py` re-runs the MCP suite against the built
wheel (or `FAVA_CANDIDATE_WHEEL` / `FAVA_CANDIDATE_SDIST` when set) so both paths
are checked on the installed artifact (#83 / #99).

## Identity configuration

Governed read isolation is **process-scoped**. See
[governed-recall.md](governed-recall.md) for the full model. Operators must:

1. Set `FAVA_TRAILS_AGENT_ID` on each ordinary authoring MCP process.
2. Keep one authenticated identity per authoring endpoint (a shared gateway
   credential is one identity boundary).
3. Enable `FAVA_TRAILS_OPERATOR=1` only on a separate operator-controlled process.
4. Reject caller `agent_id` values that do not match the configured identity.

Default `recall` / `get_thought` remain approved-current only. Authoring is
explicit and owner-scoped; history is operator-only.

Coverage:

- Source-tree lifecycle and spoof rejection: `tests/test_governance.py` (#72)
- **Two separately configured ordinary server processes** on one data repo
  (own-draft visibility + cross-process spoof rejection), including under the
  installed wheel: `tests/test_mcp_protocol.py::test_two_ordinary_server_processes_isolate_authoring`
- Packaged re-run of governance + MCP suites: `tests/test_packaged_mcp.py`

## Upgrade behavior and local runtime selectors

| Install path | What runs after `pip install -U fava-trails` |
| --- | --- |
| `command: fava-trails-server` on `PATH` | New wheel **if** PATH points at the upgraded environment |
| `uv run --directory /path/to/checkout fava-trails-server` | **Checkout tree**, not PyPI, until that directory is updated |
| Vendor / pinned clone path in client config | **Pinned tree** until the pin is moved |
| Long-lived MCP client session | Previous process until the client reloads the server |

Checklist after an upgrade:

1. `python -m pip show fava-trails` (or `uv pip show fava-trails`) in the target env.
2. `fava-trails version` and confirm package/module versions and module path.
3. Restart the MCP client registration (install alone does not replace a live process).
4. For authoring endpoints, confirm `FAVA_TRAILS_AGENT_ID` is still set on the
   process env the client actually launches.

## Release candidate verification (pre-publish)

Publication is **owner-gated** via `.github/workflows/release.yml`
(`workflow_dispatch` on an **already-pushed** immutable tag, job
`environment: fava-release` with required owner approval). The job:

1. Accepts `tag` only via job `env` (never raw shell interpolation). Validates
   strict `vMAJOR.MINOR.PATCH` grammar, fetches `refs/tags/<tag>` only (not a
   same-named branch), and fetches `refs/heads/main`. **Draft-resume state is
   resolved before the main relationship check** so a post-PyPI retry is not
   stranded when protected `main` advances after the tag was cut. First
   publication requires the peeled tag commit to equal current `origin/main`;
   an existing **draft** requires the tag commit to be an **ancestor** of
   protected `origin/main` (including equality). Detaches `HEAD` at the tag and
   asserts `git rev-parse HEAD` equals the tag peel (and equals `origin/main` on
   first publish). Package version must match the tag. Provenance uses that
   verified `HEAD` SHA — not workflow `GITHUB_SHA` from the dispatch ref.
2. Refuses a **published** GitHub Release for the tag; a **draft** Release may be
   resumed on rerun only after canonical title/notes/target are regenerated and
   verified against the candidate (not `isDraft` alone).
3. **Builds once**, records SHA-256 hashes plus `CANDIDATE_COMMIT` /
   `CANDIDATE_TAG` / `CANDIDATE_MAIN` / `CANDIDATE_MAIN_RELATION` for the wheel
   and sdist.
4. Sets `FAVA_CANDIDATE_WHEEL` / `FAVA_CANDIDATE_SDIST` to those exact files and
   runs `tests/test_packaged_mcp.py` — fresh wheel install, fresh sdist install,
   real `0.6.0` → candidate upgrade, installed-entrypoint MCP (direct stdio **and**
   native Inspector registration), two-process identity isolation, and governed
   recall (#72).
5. **Only after validation succeeds**, stages or normalizes a **draft** GitHub
   Release (wheel, sdist, `candidate-SHA256SUMS`; target/title/notes bound to the
   verified candidate), publishes **the same** `dist/` artifacts to PyPI (with
   attestations; `skip-existing` for resume), **downloads the published
   wheel+sdist and requires their SHA-256 to match `candidate-SHA256SUMS`**
   (fail closed on mismatch — `skip-existing` alone is not byte proof), then
   undrafts the Release so it becomes public only after that hash proof.
   Candidate provenance (`CANDIDATE_*`) is exported once via `$GITHUB_ENV` and
   inherited by later steps; it is not re-mapped through the empty workflow
   expression `env` context.

Validation therefore runs **before** any public GitHub Release or PyPI upload
exists. The workflow no longer triggers on `release: published`.

Local pre-authorization check (binds what you test to files you could tag):

```bash
# From an immutable reviewed commit on main / the release branch:
uv build
sha256sum dist/*.whl dist/*.tar.gz | tee candidate-SHA256SUMS
export FAVA_CANDIDATE_WHEEL=$(ls dist/*.whl)
export FAVA_CANDIDATE_SDIST=$(ls dist/*.tar.gz)
uv run pytest \
  tests/test_packaged_mcp.py \
  tests/test_governance.py \
  tests/test_mcp_protocol.py \
  tests/test_runtime_info.py -v
# After the suite: confirm hashes still match (no rebuild sneaked in)
sha256sum -c candidate-SHA256SUMS
```

`tests/test_packaged_mcp.py` uses the env-bound candidates when set; otherwise it
builds wheel + sdist itself. Either way it verifies fresh wheel install, sdist
install, upgrade from published `fava-trails==0.6.0`, and re-runs the installed
MCP + governance suites against the wheel.

Post-publication proof: download the published wheel/sdist (or use the Release
asset `candidate-SHA256SUMS`) and confirm SHA-256 matches the tested candidate
set before trusting install instructions.

Until a release is published and verified, label the work **merged but
unreleased**. After publication, confirm PyPI and GitHub release metadata match
the tested candidate, then install with:

```bash
pip install -U 'fava-trails>=0.6.1'
fava-trails version
```
