# Connect a private FAVA repository through Secure MCP Tunnel

Run one long-lived gateway for one FAVA data repository. The gateway owns a
loopback MCP server and an OpenAI `tunnel-client` process in the operator's
environment. ChatGPT reaches that server through the authenticated OpenAI tunnel;
FAVA does not need a public listening address. Existing stdio clients can continue
using `fava-trails-server` independently.

The gateway belongs to the data repository. Its lifetime and configuration must
not depend on an agent session or the current product working directory. A
service manager can supervise `fava-trails-tunnel run`; the operator supplies the
repository, credentials, executable paths, and restart policy.

## Prepare the repository and credentials

Install FAVA and JJ, then use `fava-trails clone` or `fava-trails bootstrap` as
explained in the [setup instructions](../AGENTS_SETUP_INSTRUCTIONS.md). Confirm
that the chosen directory contains the intended `config.yaml`, `trails/`, and JJ
repository, and that its remote and bookmark tracking are configured for sync.
Use a dedicated clone for this long-lived gateway when other clients have their
own working copies.

Set an absolute repository path and an ordinary server identity in the service
environment:

```bash
export FAVA_TRAILS_DATA_REPO=/absolute/path/to/fava-trails-data
export FAVA_TRAILS_AGENT_ID=private-repository-gateway
export FAVA_TRAILS_SCOPE_HINT=example/engineering  # optional discovery hint
```

Keep `FAVA_TRAILS_OPERATOR` unset on the ordinary shared endpoint. All clients of
that endpoint share its configured authoring identity; a caller-supplied
`agent_id` cannot impersonate another identity. The optional scope hint helps
clients discover context and grants no access. See [governed recall](governed-recall.md).

The repository's `config.yaml` must declare a supported Trust Gate policy.
Configure the provider, exact model, and credential source for this host; machine
settings in `~/.config/fava-trails/config.yaml` can override repository settings.
For example, with a configured OpenAI-compatible provider:

```yaml
trust_gate: llm-oneshot
trust_gate_provider: openai
trust_gate_model: YOUR_CONFIGURED_MODEL_ID
trust_gate_api_base: https://YOUR_PROVIDER_ENDPOINT/v1
trust_gate_api_key_file: /absolute/private/path/to/trust-gate-key
```

Use an owner-readable credential file supplied by the operator's secret mechanism,
not a key committed to the data repository. `trust_gate_api_key_env` is also
supported when a service injects the key through its environment. Keep the review
prompt at `trails/trust-gate-prompt.md`, or in the appropriate scope hierarchy.
The gateway checks configuration and credentials before exposing the tunnel;
actual proposal acceptance also requires the configured reviewer to respond.

## Configure and validate the tunnel

Follow OpenAI's [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
to create a tunnel in the intended Platform organization and install the official
[`tunnel-client` release](https://github.com/openai/tunnel-client/releases/latest)
for the host. The creating identity needs tunnel Read and Manage permissions;
running or selecting a tunnel needs Read and Use. ChatGPT developer-mode access
and the correct workspace/Platform association are separate requirements.

Inject the control-plane API key as `CONTROL_PLANE_API_KEY` through the service's
secret mechanism. It is separate from the Trust Gate provider key. Initialize a
named profile, substituting the assigned tunnel ID:

```bash
tunnel-client init \
  --profile private-fava \
  --tunnel-id tunnel_YOUR_ASSIGNED_ID \
  --mcp-server-url http://127.0.0.1:8765/mcp/ \
  --control-plane-api-key-ref env:CONTROL_PLANE_API_KEY \
  --health-listen-addr 127.0.0.1:0
```

Run this while no other gateway owns the selected loopback port:

```bash
fava-trails-tunnel preflight \
  --data-repo "$FAVA_TRAILS_DATA_REPO" \
  --profile private-fava --host 127.0.0.1 --port 8765 --mcp-path /mcp/ \
  --ready-timeout 45
```

Preflight validates the repository, starts the local HTTP child, verifies MCP and
data readiness, then stops that child. It does not start an external tunnel or
prove that the remote reviewer is reachable. Resolve any reported failure before
starting the service.

Start the foreground gateway using the same repository, port, and profile:

```bash
fava-trails-tunnel run \
  --data-repo "$FAVA_TRAILS_DATA_REPO" \
  --profile private-fava --host 127.0.0.1 --port 8765 --mcp-path /mcp/ \
  --ready-timeout 45 --sync-on-start --sync-interval-seconds 300
```

The supervisor starts the HTTP child, checks readiness, and then runs this
`tunnel-client` command itself:

```bash
tunnel-client run --profile private-fava
```

Do not start a second copy of that command alongside the supervisor. For a manual
tunnel-client diagnostic, stop the supervised gateway, start its HTTP child in
one terminal, and run the tunnel client in a second terminal with the same service
environment:

```bash
# Terminal 1: diagnostic child; stop it when diagnosis is complete.
fava-trails-tunnel _serve-http \
  --data-repo "$FAVA_TRAILS_DATA_REPO" \
  --profile private-fava --host 127.0.0.1 --port 8765 --mcp-path /mcp/

# Terminal 2: validate the profile and live local MCP server, then connect.
tunnel-client doctor --profile private-fava --explain
tunnel-client run --profile private-fava
```

`_serve-http` is the supervisor's internal child command, shown only for bounded
diagnosis. Stop both diagnostic processes before restarting the managed gateway.
When the managed gateway is already running, `tunnel-client doctor --profile
private-fava --explain` can inspect its profile and local target without starting
another tunnel. Use `curl --fail http://127.0.0.1:8765/healthz` for a local readiness
check. Health includes repository readiness; process existence alone is
insufficient. The startup output identifies the repository, trails directory,
loopback URL, and tunnel profile.

`--sync-on-start` requires successful repository sync before exposure. A
local-only repository with no git remote is `not_configured` and fails closed
when that flag is set; configure a reachable remote first. Periodic
sync updates the long-lived clone; use `--sync-interval-seconds 0` only if another
owned mechanism handles it. Dirty state, case collisions, merge conflicts,
unreachable remotes, or permission failures require operator attention. Do not
grant operator access to the shared MCP endpoint merely to enable ordinary `sync`.

## Connect ChatGPT and verify the workflow

In ChatGPT's developer app setup, choose a Tunnel connection and select or enter
the assigned tunnel ID. If it is unavailable, check the workspace/organization
association and tunnel permissions in the OpenAI guide. Keep approval settings
appropriate to the connected repository's data and write access.

Through the actual connected app, perform this bounded acceptance sequence:

1. Call `get_usage_guide`, then `list_scopes(prefix="example/engineering")`. Use an
   exact returned `path` as `trail_name`; a prefix is a path prefix, not partial
   text matching. Read-only lookup does not create a missing scope.
2. Call `recall` with that explicit `trail_name`, then `get_thought` for an exact
   returned ID. Default reads should contain only current approved records.
3. With an operator-approved synthetic example, call `save_thought` in an intended
   scope. Default reads must hide the new draft; `mode="authoring"` can retrieve
   it through the same configured identity.
4. Call `propose_truth`. Confirm a real configured Trust Gate result and recorded
   approval provenance. A failed or rejected review is not successful approval.
5. Call ordinary `sync`, then retrieve the approved ID through default
   `get_thought`. Restart the gateway service and repeat that read to check
   persistence and reconnection.

Ordinary clients cannot use operator history, `forget`, or `rollback`, or claim a
different author identity. Keep any separate administrative endpoint under
operator control. Server-side failures are returned as structured tool results;
SDK input validation failures use MCP's error result. Automated HTTP coverage in
`tests/test_gateway_workflow.py` exercises the workflow against temporary JJ/Git
repositories with only the external LLM result substituted. Live acceptance must
use the real provider and connected client to establish those additional facts.

## Deployment boundaries

The loopback server has no standalone public authentication boundary. Do not
expose private FAVA data on a public endpoint without separately designed
authentication, authorization, and hosting controls.

This v1 path covers one repository-owned gateway through OpenAI Secure MCP
Tunnel. Per-agent aggregation, per-machine registries, Tailscale Aperture
integration, Cloudflare Tunnel as the mainline path, WiseMachine host assumptions,
and public HTTPS hosting are outside this path. Host-specific container and
service runbooks belong to the deploying project. This guide does not authorize
public publication or data migration.
