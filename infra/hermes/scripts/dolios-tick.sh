#!/bin/bash
# autonomous-coder tick wrapper.
#
# `hermes cron create --script <name>` resolves <name> under the PROFILE's
# scripts dir — ~/.hermes/profiles/autonomous-coder/scripts/ on the host
# (in-container: /opt/data/profiles/autonomous-coder/scripts/). We keep the
# wrapper here in the dolios repo for versioning; `make install-coder-cron`
# installs it at that path.
#
# Mode: --no-agent. The script IS the cron job; its stdout is delivered
# verbatim. No LLM in the orchestration loop — tick.py is fully
# deterministic, and that's the whole point of factoring it out.
#
# REPOS_ROOT: docker-compose's `environment:` sets this on the gateway PID 1,
# but hermes-agent re-loads the profile .env (which has the host value
# /home/steve/repos for host-mode runs) when it spawns this script as a cron
# child — so the gateway-level env is shadowed. The wrapper IS the container
# path, so we set it here explicitly to win the precedence race.
set -e
export REPOS_ROOT=/opt/data/repos
exec python3 /opt/data/repos/dolios/services/coder/tick.py "$@"
