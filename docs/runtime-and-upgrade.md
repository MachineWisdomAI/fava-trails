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

Direct stdio probes (raw JSON-RPC over the `fava-trails-server` entrypoint)
exercise the process binary. A native client registration also loads that same
entrypoint from the client's config; installing a wheel does not update a
running client until the registration is restarted. Coverage for both paths
lives in `tests/test_mcp_protocol.py` and `tests/test_packaged_mcp.py` (#83).

## Identity configuration

Governed read isolation is process-scoped. See
[governed-recall.md](governed-recall.md) for the full model. Operators must:

1. Set `FAVA_TRAILS_AGENT_ID` on each ordinary authoring MCP process.
2. Keep one authenticated identity per authoring endpoint (a shared gateway
   credential is one identity boundary).
3. Enable `FAVA_TRAILS_OPERATOR=1` only on a separate operator-controlled process.
4. Reject caller `agent_id` values that do not match the configured identity.

Default `recall` / `get_thought` remain approved-current only. Authoring is
explicit and owner-scoped; history is operator-only. Acceptance coverage for
these behaviors is `tests/test_governance.py` (#72), also executed against the
built wheel in `tests/test_packaged_mcp.py`.

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

Publication is tag-driven (`release.yml` on a GitHub Release). Before
authorization:

```bash
# From an immutable reviewed commit on main / the release branch:
uv build
uv run pytest tests/test_packaged_mcp.py tests/test_governance.py tests/test_mcp_protocol.py tests/test_runtime_info.py -v
```

`tests/test_packaged_mcp.py` builds wheel + sdist, verifies a fresh install,
upgrades an isolated env from published `fava-trails==0.6.0`, and re-runs the
installed-entrypoint MCP and governed-recall suites against the wheel.

Until a release is published and verified, label the work **merged but
unreleased**. After publication, confirm PyPI and GitHub release metadata match
the tested candidate, then install with:

```bash
pip install -U 'fava-trails>=0.6.1'
fava-trails version
```
