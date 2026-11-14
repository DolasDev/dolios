#!/bin/bash
# autonomous-coder loop watchdog — hourly, independent of the tick.
#
# tick.py already runs the watchdog after every tick, but a tick can't notice
# that ticks have STOPPED (cron dead, tick killed before logging). This job
# runs the full check set, including `stale`, and pages over Matrix
# (MATRIX_HOMESERVER / MATRIX_ACCESS_TOKEN / MATRIX_ALERT_ROOM from the
# profile .env). Installed by `make install-coder-cron`; register with:
#   hermes -p autonomous-coder cron create '15 * * * *' --no-agent \
#     --script dolios-watchdog.sh --name dolios-coder-watchdog \
#     --workdir /opt/data/repos/dolios
#
# HOME / REPOS_ROOT: same overrides as dolios-tick.sh — hermes runs cron
# scripts with HOME=$HERMES_HOME/home and re-loads the profile .env.
set -e
export HOME=/opt/data
export REPOS_ROOT=/opt/data/repos
exec python3 /opt/data/repos/dolios/services/coder/watchdog.py "$@"
