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
#
# HOME: hermes runs cron scripts with HOME=$HERMES_HOME/home (per-profile
# home, see hermes_constants.get_subprocess_home). That dir has no .gitconfig,
# so `git push` had no gh credential helper and failed with rc 128 (the
# 2026-06-01 and 2026-11-14 chunk-3 failures). The container's real HOME is
# /opt/data, where cont-init 03-gh-git-setup writes the git/gh config and
# where ~/.claude/.credentials.json lives — restoring it also keeps the usage
# gate's atomic token refresh writing the real credentials file instead of
# replacing the profile-home symlink with a divergent copy.
set -e
export HOME=/opt/data
export REPOS_ROOT=/opt/data/repos
exec python3 /opt/data/repos/dolios/services/coder/tick.py "$@"
