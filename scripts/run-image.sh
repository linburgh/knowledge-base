#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

IMAGE_NAME="${IMAGE_NAME:-knowledge-base-backend}"
IMAGE_TAG="${IMAGE_TAG:-local}"
CONTAINER_NAME="${CONTAINER_NAME:-knowledge-base-backend}"
NETWORK_NAME="${NETWORK_NAME:-knowledge-base-net}"
HOST_PORT="${HOST_PORT:-28003}"

cd "${PROJECT_DIR}"
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env"
  set +a
fi

IMAGE_NAME="${IMAGE_NAME}" IMAGE_TAG="${IMAGE_TAG}" bash scripts/build-image.sh

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  docker network create "${NETWORK_NAME}" >/dev/null
fi

DOCKER_ENV_ARGS=()
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  DOCKER_ENV_ARGS+=(--env-file "${PROJECT_DIR}/.env")
  while IFS="=" read -r variable_name variable_value; do
    if [[ "${variable_name}" == KB_* ]]; then
      DOCKER_ENV_ARGS+=(--env "${variable_name}=${variable_value}")
    fi
  done < <(env)
fi

docker run \
  --detach \
  --name "${CONTAINER_NAME}" \
  --network "${NETWORK_NAME}" \
  --publish "${HOST_PORT}:28003" \
  --restart unless-stopped \
  "${DOCKER_ENV_ARGS[@]}" \
  "${IMAGE_NAME}:${IMAGE_TAG}"

echo "Started ${CONTAINER_NAME} from ${IMAGE_NAME}:${IMAGE_TAG}"
