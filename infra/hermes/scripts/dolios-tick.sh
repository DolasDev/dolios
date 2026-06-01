#!/bin/bash
# autonomous-coder tick wrapper.
#
# `hermes cron create --script` requires its script to live under
# ~/.hermes/scripts/ (in-container: /opt/data/scripts/), so we keep the
# wrapper here in the dolios repo for versioning and a HOST_BRINGUP step
# installs it as a symlink (or copy) at the path hermes expects.
#
# Mode: --no-agent. The script IS the cron job; its stdout is delivered
# verbatim. No LLM in the orchestration loop — tick.py is fully
# deterministic, and that's the whole point of factoring it out.
set -e
exec python3 /opt/data/repos/dolios/services/coder/tick.py "$@"
