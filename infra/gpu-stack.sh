#!/usr/bin/env bash
# Manage the Dolios LLM (Ollama) stack on the GPU box.
#
#   gpu-stack.sh up       free the GPU, then serve our model
#   gpu-stack.sh down     stop the Dolios Ollama stack
#   gpu-stack.sh status   show GPU memory + running containers
#
# The single RTX 3060 hosts only one model server at a time. `up` first stops
# any OTHER Docker container that reserves the NVIDIA GPU (and any stray native
# `ollama serve`), then brings up our stack. This repo manages only its own
# containers; anything else holding the GPU is simply stopped (reversibly —
# `docker start <name>` brings it back) so we can claim the card.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LLM_COMPOSE="$REPO_ROOT/compose.dolo-llm.yml"

free_gpu() {
  # Stop a stray native server first (it would hold :11434 from the container).
  pkill -f "ollama serve" 2>/dev/null || true
  # Stop any running container that reserves the NVIDIA GPU, except our own.
  for id in $(docker ps -q); do
    name=$(docker inspect "$id" --format '{{.Name}}' | sed 's#^/##')
    case "$name" in *ollama*) continue ;; esac   # don't stop ourselves
    if docker inspect "$id" \
        --format '{{range .HostConfig.DeviceRequests}}{{.Driver}}{{end}}' \
        | grep -qi nvidia; then
      echo ">> freeing GPU: stopping $name"
      docker stop "$id" >/dev/null
    fi
  done
}

case "${1:-}" in
  up)
    free_gpu
    echo ">> starting Dolios Ollama stack"
    docker compose -f "$LLM_COMPOSE" up -d
    ;;
  down)
    echo ">> stopping Dolios Ollama stack"
    docker compose -f "$LLM_COMPOSE" stop
    ;;
  status)
    echo "=== running containers ==="
    docker ps --format '{{.Names}}\t{{.Status}}'
    echo "=== GPU memory ==="
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
    ;;
  *)
    echo "usage: $0 {up|down|status}"; exit 2 ;;
esac
