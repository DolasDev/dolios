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

The simplest first-login path is an SSH tunnel from your laptop plus
[Element web](https://app.element.io); the TLS reverse proxy below is the
follow-on once you want phone/native clients without tunneling.

```bash
# Laptop — leave open while logging in
ssh -L 6167:127.0.0.1:6167 dolo-docker
```

In Element web: **Sign in → Edit homeserver → `http://localhost:6167` →
Continue → log in as `steve` with your password**. Start a chat with
`@autonomous-coder:dolo-docker.tail9d4ce8.ts.net`, send anything, hermes
replies. Once that works you can use the in-app password change to set
something memorable.

## TLS via `tailscale serve` (no reverse proxy needed)

For phone/native clients (or just so you don't have to keep an SSH tunnel
open), expose Conduit on `https://dolo-docker.tail9d4ce8.ts.net` via
[Tailscale Serve](https://tailscale.com/kb/1242/tailscale-serve). It
terminates TLS itself, auto-renews the Let's Encrypt cert through Tailscale's
CA path, binds to the tailnet only (not the public internet), and persists
across reboots — no Caddy/nginx, no cert files on disk, no renewal cron.

**One-time tailnet setup** (admin console):

1. Enable Serve at <https://login.tailscale.com/admin/acls/file> (Acls →
   "TailscaleAdmin" feature, or follow the deep link Tailscale prints when
   you first run `tailscale serve`).
2. Enable HTTPS certificates if not already on (same console).
3. On the host: `sudo tailscale set --operator=$USER` once, so `tailscale
   serve` / `tailscale cert` don't need sudo afterwards.

**Wire up the proxy** (host, one command):

```bash
tailscale serve --bg http://127.0.0.1:6167
```

That's it. Verify:

```bash
curl -sS https://dolo-docker.tail9d4ce8.ts.net/_matrix/client/versions
tailscale serve status
```

The first call should return the Matrix `versions` array; the second should
show `https://dolo-docker.tail9d4ce8.ts.net → proxy http://127.0.0.1:6167
(tailnet only)`.

In Element, swap the homeserver URL from `http://localhost:6167` (the
tunneled path from Step 5 above) to `https://dolo-docker.tail9d4ce8.ts.net`
and log in normally. The SSH tunnel can stay closed.

To turn the proxy off: `tailscale serve --https=443 off`.

## Admin commands (no wipe, no rebuild)

Conduit auto-makes **the first registered account** an admin and auto-joins
it to the "<server>.tail9d4ce8.ts.net Admin Room" with the server bot
`@conduit:<server>`. We register the hermes bot first, so the bot's access
token (already in `MATRIX_ACCESS_TOKEN`) is also an admin token.

To run an admin command, send a message to the admin room prefixed with
`@conduit:<server>:`. The room ID for this server is currently
`!ipgwZvBhY6v921wa9n:dolo-docker.tail9d4ce8.ts.net`. Useful commands:

| Command | What it does |
| --- | --- |
| `help` | List every admin command. |
| `help <cmd>` | Per-command usage. |
| `list-local-users` | All registered accounts. |
| `reset-password <user>` | Generate a new random password for `<user>` (printed in the reply). Use this when someone forgets a password — no need to wipe the volume. |
| `deactivate-user @user:<server>` | Deactivate an account. |
| `allow-registration true\|false` | Toggle registration without a container restart. Does NOT persist across restarts — for that, edit the compose env. |
| `create-user <name>` | Mint a new user without re-opening registration. |

Quick recipe — reset `@steve`'s password from the host:

```bash
TOKEN=$(grep -E '^MATRIX_ACCESS_TOKEN=' ~/.hermes/profiles/autonomous-coder/.env | cut -d= -f2-)
ROOM='!ipgwZvBhY6v921wa9n:dolo-docker.tail9d4ce8.ts.net'
ENC=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ROOM")
TXN=$(date +%s%N)
curl -sS -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  "http://127.0.0.1:6167/_matrix/client/v3/rooms/$ENC/send/m.room.message/$TXN" \
  -d '{"msgtype":"m.text","body":"@conduit:dolo-docker.tail9d4ce8.ts.net: reset-password steve"}'
# Wait a second, then pull @conduit's reply:
curl -sS -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:6167/_matrix/client/v3/rooms/$ENC/messages?dir=b&limit=2" | python3 -m json.tool
```

## Operating notes

- **Backups.** RocksDB lives in the `matrix_data` volume. Snapshot it the same
  way you snapshot `pgdata`. Conduit can be restored by dropping the volume
  back in place. Wiping the volume is only the right move if the DB itself is
  corrupted — for forgotten passwords or stuck accounts, use the admin room
  above instead (no rebuild, no bot token rotation).
- **Bumping Conduit.** Change the image tag in `docker-compose.yml`
  (`matrixconduit/matrix-conduit:vX.Y.Z`) and `docker compose up -d matrix`.
  Conduit is still pre-1.0; pin a specific tag, don't track `latest`. Watch the
  startup welcome-changelog in the logs — Conduit shouts about every released
  version after yours, including CVE fixes, so it's easy to spot when to bump.
- **Login probe is not user enumeration.** Conduit returns identical
  `M_FORBIDDEN: Wrong username or password` for "wrong password" and
  "no such user" — anti-enumeration. To check whether an account exists, ask
  `@conduit: list-local-users` in the admin room.
- **Federation.** Stay off unless you have a reason. Flipping it on requires
  public DNS for the server name, an `.well-known/matrix/server` file, and a
  publicly reachable port — none of which you want for a fleet-internal bus.
- **E2EE.** The mautrix SDK in the hermes image is built with `libolm` so the
  bot *can* participate in encrypted rooms. With federation off and a closed
  user list on a Tailscale-only homeserver, E2EE is belt-and-braces; the
  unencrypted DM path is fine for fleet chat.
