# Self-hosted Matrix (Conduit) for the Dolios fleet

A single-node, **Tailscale-only**, **federation-off** Matrix homeserver that
gives you (and any other allowlisted human) a real chat client to talk to the
hermes-agent employees. No public DNS, no inbound holes in your router, no
content ever leaves the tailnet.

| Piece | Choice | Why |
| --- | --- | --- |
| Homeserver | [Conduit](https://gitlab.com/famedly/conduit) | Single Rust binary, RocksDB; no Postgres, no Synapse complexity. |
| Transport | Tailscale | All clients (Element on phone/laptop, the hermes container) are on the tailnet anyway. |
| TLS | Tailscale-issued cert | `tailscale cert dolo-docker.tail9d4ce8.ts.net` — no Let's Encrypt, no public DNS. |
| Federation | Off | `CONDUIT_ALLOW_FEDERATION=false`. No `.well-known`, no SRV. |
| Registration | Off by default | Flip on **once** to create accounts, then flip off. |
| Auth from hermes | Long-lived **access token** | `MATRIX_HOMESERVER` + `MATRIX_ACCESS_TOKEN` in the profile `.env`. |

## Bring-up (one-time)

### 1. Bring Conduit up with registration open

```bash
# On dolo-docker
cd ~/repos/dolios
CONDUIT_ALLOW_REGISTRATION=true docker compose up -d matrix
docker compose logs -f matrix          # wait for "Conduit ready"
```

The compose binds Conduit only to `127.0.0.1:6167` on the host. For first-time
registration, port-forward over SSH from your laptop:

```bash
ssh -L 6167:127.0.0.1:6167 dolo-docker
# Then point Element web at http://localhost:6167 (homeserver URL).
```

### 2. Register the bot account and your human account

Use Element's "Create account" flow at the homeserver URL above, or register
via curl:

```bash
# Bot account — the hermes-agent identity
curl -X POST http://127.0.0.1:6167/_matrix/client/v3/register \
  -H 'Content-Type: application/json' \
  -d '{
    "username": "autonomous-coder",
    "password": "<long random>",
    "auth": {"type": "m.login.dummy"},
    "device_id": "DOLIOS-COMPOSE"
  }'
# Response contains "access_token" — copy it.
```

Repeat for your own human account (`steve` or similar).

### 3. Close registration

```bash
# Edit docker-compose.yml: CONDUIT_ALLOW_REGISTRATION defaults to false now,
# so just unset the env override and restart.
unset CONDUIT_ALLOW_REGISTRATION
docker compose up -d matrix
```

### 4. Plumb the token into the autonomous-coder profile

```bash
cat >> ~/.hermes/profiles/autonomous-coder/.env <<'EOF'
MATRIX_HOMESERVER=http://matrix:6167
MATRIX_ACCESS_TOKEN=<token from step 2>
MATRIX_ALLOWED_USERS=@steve:dolo-docker.tail9d4ce8.ts.net
EOF
docker compose restart hermes-autonomous-coder
```

`MATRIX_HOMESERVER=http://matrix:6167` is the in-network address — the hermes
container reaches Conduit over the compose network, not via the tailnet.
`MATRIX_ALLOWED_USERS` is hermes-agent's allowlist for which Matrix IDs may
send the agent commands; everyone else is ignored.

### 5. Start a DM from your Element client to the bot

On your phone/laptop Element, set the homeserver to
`https://dolo-docker.tail9d4ce8.ts.net` (see TLS note below), log in as
yourself, start a DM with `@autonomous-coder:dolo-docker.tail9d4ce8.ts.net`,
and send `hi`. Hermes should reply.

## TLS via Tailscale (recommended for clients)

Element clients want HTTPS. Issue a Tailscale-managed cert on the dolo-docker
host (one-time):

```bash
sudo tailscale cert dolo-docker.tail9d4ce8.ts.net
# Produces dolo-docker.tail9d4ce8.ts.net.crt + .key in the current dir.
```

Then put any reverse proxy (Caddy, nginx, traefik) in front of Conduit on
port 443, terminating TLS with that cert and forwarding to
`http://127.0.0.1:6167`. Setting that up is out of scope here — it's a single
HTTPS upstream and isn't Dolios-specific.

For a quick "does it work" check before you wire the proxy, you can skip TLS
entirely and point Element at `http://127.0.0.1:6167` via the SSH tunnel from
step 1.

## Operating notes

- **Backups.** RocksDB lives in the `matrix_data` volume. Snapshot it the same
  way you snapshot `pgdata`. Conduit can be restored by dropping the volume
  back in place.
- **Bumping Conduit.** Change the image tag in `docker-compose.yml`
  (`matrixconduit/matrix-conduit:vX.Y.Z`) and `docker compose up -d matrix`.
  Conduit is still pre-1.0; pin a specific tag, don't track `latest`. Watch the
  startup welcome-changelog in the logs — Conduit shouts about every released
  version after yours, including CVE fixes, so it's easy to spot when to bump.
- **Federation.** Stay off unless you have a reason. Flipping it on requires
  public DNS for the server name, an `.well-known/matrix/server` file, and a
  publicly reachable port — none of which you want for a fleet-internal bus.
- **E2EE.** The mautrix SDK in the hermes image is built with `libolm` so the
  bot *can* participate in encrypted rooms. With federation off and a closed
  user list on a Tailscale-only homeserver, E2EE is belt-and-braces; the
  unencrypted DM path is fine for fleet chat.
