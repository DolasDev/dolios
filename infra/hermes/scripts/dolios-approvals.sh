#!/bin/bash
# Entry point the hermes CHAT agent uses for proposal decisions:
#   dolios-approvals.sh list
#   dolios-approvals.sh decide <name> approve|park|abandon [--note "..."]
#
# Why a wrapper: the chat agent's terminal tool runs with a stripped
# environment — `python3` resolves to /usr/bin/python3 (no pyyaml) and the
# MATRIX_* / GH_TOKEN vars from the profile .env are filtered out. On
# 2026-11-16 that made `decide` fail, and the model then improvised by
# hand-editing approvals.py and the proposal in the shared checkout, which
# blocked every tick's sync for a week. This wrapper pins the interpreter
# and loads the env itself so the documented command just works.
# Installed by `make install-coder-cron`.
set -e
export HOME=/opt/data
export REPOS_ROOT=/opt/data/repos
ENV_FILE=/opt/data/profiles/autonomous-coder/.env
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi
PY=/opt/hermes/.venv/bin/python3
[ -x "$PY" ] || PY=python3
exec "$PY" /opt/data/repos/dolios/services/coder/approvals.py "$@"
