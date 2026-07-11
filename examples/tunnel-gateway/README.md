# FAVA Tunnel Gateway Example

This is a generic Compose command example, not a canonical deployment.

Run a non-exposing check before the service is started:

```bash
docker compose run --rm fava-tunnel \
  fava-trails-tunnel preflight \
  --data-repo "$FAVA_DATA_REPO" \
  --profile "$FAVA_TUNNEL_PROFILE" \
  --tunnel-doctor
```

The service performs one startup sync and sets the interval to zero, so it does
not run recurring synchronization. After startup, its private readiness endpoint
is available at `http://127.0.0.1:8765/healthz` inside the service network.

Production deployments must independently provision credentials, initialize the
data repository, and select persistent storage appropriate to their environment.
