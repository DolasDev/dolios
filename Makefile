# Convenience targets for the dolios stack.
#
# `up`, `down`, `logs`, etc. operate on the host stack (hermes + chat-ui + db).
# `llm-*` targets operate on the dolo-llm stack and are intended to be run
# *on the dolo-llm machine itself* after this repo is checked out there.

.PHONY: up down restart build logs ps \
        llm-up llm-down llm-logs llm-ps \
        env

up:
	docker compose up -d --build

down:
	docker compose down

restart: down up

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

llm-up:
	docker compose -f compose.dolo-llm.yml up -d

llm-down:
	docker compose -f compose.dolo-llm.yml down

llm-logs:
	docker compose -f compose.dolo-llm.yml logs -f

llm-ps:
	docker compose -f compose.dolo-llm.yml ps

env:
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example — edit it before `make up`.")
