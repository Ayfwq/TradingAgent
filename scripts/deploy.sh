#!/usr/bin/env bash
# Run on the Linux server from any directory: bash scripts/deploy.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env ]]; then
  echo "Missing .env. Copy .env.example to .env and set the API key and POSTGRES_PASSWORD." >&2
  exit 1
fi

if ! grep -Eq '^POSTGRES_PASSWORD=.+$' .env; then
  echo "Set a non-empty POSTGRES_PASSWORD in .env before deploying." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "The checkout has local changes. Commit or move them before deploying." >&2
  exit 1
fi

if [[ "$(git branch --show-current)" != master ]]; then
  echo "Deploy from the master branch checkout." >&2
  exit 1
fi

echo "Fetching GitHub master..."
git fetch origin master
if [[ "${1:-}" == "--only-if-changed" && -f .deploy-revision && "$(cat .deploy-revision)" == "$(git rev-parse origin/master)" ]]; then
  echo "Already at the latest GitHub commit; nothing to deploy."
  exit 0
fi
git merge --ff-only origin/master

echo "Validating Compose configuration..."
docker compose config --quiet

echo "Building the application image (Docker reuses cached dependency layers)..."
docker compose build tradingagents

echo "Starting services and waiting for health checks..."
docker compose up -d --remove-orphans --wait --wait-timeout 300
docker compose ps
git rev-parse HEAD > .deploy-revision
echo "Deployed $(git rev-parse --short HEAD)"
