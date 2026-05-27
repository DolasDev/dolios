# Containerized hermes-agent

The hermes-agent employees run as Docker containers on dolo-docker, alongside
the fleet Postgres (see the top-level [`docker-compose.yml`](../../docker-compose.yml)).
This replaces the earlier native `curl | bash` install — the agent now matches
the rest of the stack: pinned, reproducible from the repo, and sandboxed away
from the host's user, credentials, and filesystem.

## Why containerized

The `autonomous-coder` is an *autonomous* agent that runs `git`, `gh`, `claude`,
and arbitrary shell commands. Native, it had the host user's full privileges and
filesystem; in a container its blast radius is the volumes we mount and nothing
more. It also pins versions and aligns with the project's IaC mission — the
native install was the least reproducible part of the whole stack.

## The image

[`Dockerfile`](Dockerfile) is a **thin layer** over Nous Research's official
published image (`docker.io/nousresearch/hermes-agent`, pinned by digest). That
base brings s6-overlay supervision, a non-root runtime with `HERMES_UID` remap,
and `/init` as PID 1. We add only the two tools the base omits but the coder
dispatcher needs:

- **`gh`** — opens pull requests.
- **`claude`** (Claude Code) — the headless engineer the supervisor dispatches
  the actual code changes to.

Everything else (node, git, ripgrep, docker-cli) is already in the base.

## Runtime wiring (compose service `hermes-autonomous-coder`)

| Concern | How |
|---|---|
| **State / profile** | Bind-mount `~/.hermes` → `/opt/data` (`HERMES_HOME`). The host dir, materialized by `make employee`, stays the source of truth; the image is stateless. |
| **Claude creds** | Bind-mount `~/.claude` → `/opt/data/.claude` (container `HOME` is `/opt/data`). RW so OAuth refresh persists. |
| **Model (dolo-llm)** | It's a Tailscale node, so a bridged container can't use the host's MagicDNS — `extra_hosts` maps `dolo-llm` → its tailnet IP (`100.69.252.113`). Update if that IP changes. |
| **Postgres** | Same compose project/network as `db`; reachable as `db:5432`. |
| **File ownership** | `HERMES_UID/GID=1000` remaps the in-container user to the host owner of `~/.hermes`, so created files stay host-usable. |
| **Secrets** | `env_file` the profile `.env` — `OPENROUTER_API_KEY` (fallback) and `GH_TOKEN` (PRs). |
| **Process** | `command: gateway run --profile autonomous-coder` — the always-on supervisor, scoped to this employee. Idles until the `coder_loop` cron is enabled in the profile `config.yaml` (HOST_BRINGUP step 6). `--profile` sets `HERMES_HOME` in-process (after the s6 hooks run against `/opt/data`); we can't lead with `-p` because the wrapper routes on the first arg. |

## Usage

```sh
make up                      # builds (first time) + starts db + hermes-autonomous-coder
make coder-logs              # follow the agent
# One-shot / interactive, on demand. `run` overrides the service command, so pass
# --profile yourself. The wrapper routes on the FIRST arg and chokes on a leading
# `-p`, so lead with the subcommand and put --profile after it (hermes honours it
# anywhere in argv):
docker compose run --rm hermes-autonomous-coder chat -q "who are you?" --profile autonomous-coder
docker compose run --rm hermes-autonomous-coder --tui --profile autonomous-coder
```

## Still required before the PR path works

- **`GH_TOKEN`** in `~/.hermes/profiles/autonomous-coder/.env` — the container
  has no host `gh` auth to inherit (gh isn't installed on the host at all).
  A fine-grained PAT with `contents` + `pull_requests` write on the allowlisted
  repos. See [`../../employees/autonomous-coder/env.example`](../../employees/autonomous-coder/env.example).
- **Repo checkouts** mounted in (the commented `~/repos` volume) once the
  dispatcher allowlist (`services/coder/coder.yaml`) is filled in — HOST_BRINGUP
  step 5.

## Bumping versions

- **Base image:** pull the new digest from `docker.io/nousresearch/hermes-agent`
  (tag `main`) and replace it in the `FROM` line.
- **Claude Code:** bump `CLAUDE_CODE_VERSION` to match the host (`claude --version`).

Then `make up` (compose rebuilds on the changed `Dockerfile`).
