#!/bin/bash
# Morning Matrix digest of proposals waiting on a human decision.
#
# Lists every `status: proposed` proposal (minus parked ones) with its plain-
# English `pitch:` and the reply commands (`approve <name>` / `park <name>` /
# `abandon <name>`), which the hermes chat agent applies via
# `approvals.py decide`. Sends nothing when nothing is pending. Installed by
# `make install-coder-cron`; register with:
#   hermes -p autonomous-coder cron create '0 13 * * *' --no-agent \
#     --script dolios-approvals-digest.sh --name dolios-approvals-digest \
#     --workdir /opt/data/repos/dolios
# (13:00 UTC = 7:00 CST / 8:00 CDT — after the last overnight tick.)
#
# HOME / REPOS_ROOT: same overrides as dolios-tick.sh (gh/git config lives
# under /opt/data, not the per-profile cron HOME).
set -e
export HOME=/opt/data
export REPOS_ROOT=/opt/data/repos
exec python3 /opt/data/repos/dolios/services/coder/approvals.py digest "$@"
