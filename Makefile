# Convenience targets for the dolios stack.
#
# Host stack (`up`, `down`, `logs`, `ps`) is Postgres + the containerized
# hermes-agent employees (see infra/hermes/ and docker-compose.yml).
# `llm-*` targets operate on the dolo-llm stack and are intended to be run
# *on the dolo-llm machine itself* after this repo is checked out there.
#
# The single RTX 3060 hosts one model server at a time, so `llm-up` frees the
# GPU (stops any other container reserving it) before serving — see
# infra/gpu-stack.sh.

SWITCH := ./infra/gpu-stack.sh

.PHONY: up down restart logs coder-logs ps env \
        llm-up llm-down llm-logs llm-ps gpu-status \
        usage usage-decide usage-test employee \
        coder-preflight coder-test \
        audit audit-gaps audit-test \
        backlog-next backlog-test

up:
	docker compose up -d

down:
	docker compose down

restart: down up

logs:
	docker compose logs -f

# Follow just the autonomous-coder container.
coder-logs:
	docker compose logs -f hermes-autonomous-coder

ps:
	docker compose ps

# Free the GPU (stop other GPU containers), then bring up the Dolios LLM stack.
llm-up:
	$(SWITCH) up

llm-down:
	$(SWITCH) down

llm-logs:
	docker compose -f compose.dolo-llm.yml logs -f

llm-ps:
	docker compose -f compose.dolo-llm.yml ps

# Show running containers + VRAM usage.
gpu-status:
	$(SWITCH) status

env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit it before \`make up\`.")

# Spare-capacity gate — the orchestrator's pre-dispatch check. See
# services/usage-gate/README.md.
usage:
	@python3 services/usage-gate/usage_gate.py

# Emit a dispatch/hold decision; exits 1 on hold so shell can branch on $?.
usage-decide:
	@python3 services/usage-gate/usage_gate.py --decide

usage-test:
	@cd services/usage-gate && python3 test_usage_gate.py

# Materialize a checked-in employee spec into a hermes-agent profile.
#   make employee ROLE=autonomous-coder
#   DRY_RUN=1 make employee ROLE=autonomous-coder
employee:
	@test -n "$(ROLE)" || (echo "usage: make employee ROLE=<role> (see employees/)"; exit 2)
	@./scripts/materialize-employee.sh $(ROLE)

# autonomous-coder dispatcher (services/coder/). Needs coder.yaml on the host.
coder-preflight:
	@python3 services/coder/dispatch.py --preflight-only

coder-test:
	@cd services/coder && python3 test_dispatch.py

# Repo health audit — the deterministic half of the discovery loop. Appends a
# snapshot to .dolios/metrics/dolios/history.jsonl. See services/auditor/ and
# docs/metrics.md.
audit:
	@python3 services/auditor/audit.py --repo . --name dolios \
	  --history .dolios/metrics/dolios/history.jsonl

# Just the ranked gaps (no full snapshot). Useful for spot-checks.
audit-gaps:
	@python3 services/auditor/audit.py --repo . --name dolios --gaps

audit-test:
	@cd services/auditor && python3 test_audit.py

# Deterministic priority picker — what the supervisor cron runs each tick.
# Emits JSON: kind ∈ {audit, propose, empty, error}. See services/coder/backlog.py.
backlog-next:
	@python3 services/coder/backlog.py --next

backlog-test:
	@cd services/coder && python3 test_backlog.py
