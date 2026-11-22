#!/usr/bin/env bash
# Start Power Hour Studio in Docker, using the NVIDIA GPU automatically when this machine has one.
#
# A GPU request makes Docker refuse to start containers on machines without NVIDIA, so the GPU
# override (docker-compose.gpu.yml) can't just always be on. This picks the right files:
#   GPU used  = an NVIDIA GPU is visible to the host driver AND Docker has the NVIDIA runtime
#   otherwise = plain docker-compose.yml (CPU encoding; fine on Mac and CPU-only machines)
#
# Usage: scripts/docker-up.sh [--dry-run] [docker compose args...]   (default: up --build -d)
#   PH_FORCE_CPU=1 scripts/docker-up.sh   # never use the GPU
set -euo pipefail
cd "$(dirname "$0")/.."

dry_run=0
if [ "${1:-}" = "--dry-run" ]; then dry_run=1; shift; fi

has_nvidia_gpu() {
    [ "${PH_FORCE_CPU:-0}" = "1" ] && return 1
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 || return 1
    docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -qi nvidia
}

files=(-f docker-compose.yml)
if has_nvidia_gpu; then
    files+=(-f docker-compose.gpu.yml)
    echo "NVIDIA GPU + Docker NVIDIA runtime detected: GPU encoding enabled."
else
    echo "No usable NVIDIA GPU for Docker: using CPU encoding."
fi

args=("$@")
[ ${#args[@]} -eq 0 ] && args=(up --build -d)

if [ "$dry_run" = "1" ]; then
    echo "docker compose ${files[*]} ${args[*]}"
else
    exec docker compose "${files[@]}" "${args[@]}"
fi
