# cont-init.d hooks must use `#!/command/with-contenv sh`, not `#!/bin/sh`

## Context

PR #3 was opened from the host as a one-time bridge after the first
container-based dispatch (`bnbaohlmq`, 2026-06-01) couldn't `git push`.
Triage showed `gh-git-setup` cont-init hook ran cleanly but logged "GH_TOKEN
not set — skipping," even though `docker compose exec ... env` confirmed
`GH_TOKEN` was set in the running container. `/proc/1/environ` had only
`PATH` — s6-overlay's PID 1 sanitizes the env to a minimum by design.

## Lesson

Any cont-init.d script that needs the docker-set environment (anything from
`env_file:` or `environment:` in compose) must declare `#!/command/with-contenv sh`
as its shebang. `with-contenv` is s6-overlay's wrapper that re-injects the
docker env into the script. Verified against the bundled Nous cont-init
hooks (`02-reconcile-profiles`, `015-supervise-perms`) — both use this
shebang for the same reason.

A second related gotcha: when going through `s6-setuidgid hermes` inside a
cont-init script, `s6-setuidgid` sets uid/gid but does NOT change `HOME`.
Prefix the command with `HOME=/opt/data` (the hermes user's home in our
setup) or gh/git will read/write to `/root/...` and fail or persist nothing.

## Apply to

Any future proposal that adds a cont-init.d hook for this profile or any
sibling profile. Check both the shebang and the `HOME=` prefix for any
`s6-setuidgid` invocation. If a hook is logging "env var not set" while
that var is clearly set in the container, this is the first thing to check.
