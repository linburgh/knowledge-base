#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-knowledge-base-backend}"
IMAGE_TAG="${IMAGE_TAG:-local}"

docker build \
  --file Dockerfile \
  --tag "${IMAGE_NAME}:${IMAGE_TAG}" \
  .

echo "Built ${IMAGE_NAME}:${IMAGE_TAG}"
