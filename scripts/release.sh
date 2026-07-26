#!/usr/bin/env bash
set -euo pipefail
VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "Usage: ./scripts/release.sh <version>"
  exit 1
fi
TAG="v${VERSION}"
echo "=== Praxic Release ${TAG} ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "[ERROR] Working directory not clean. Commit or stash first."
  exit 1
fi
echo "[1/4] Bumping version to ${VERSION}..."
sed -i "s/version = \".*\"/version = \"${VERSION}\"/" pyproject.toml
echo "[2/4] Committing and tagging..."
git add pyproject.toml
git commit -m "release: ${TAG}"
git tag -a "${TAG}" -m "Release ${TAG}"
echo "[3/4] Pushing..."
git push origin main
git push origin "${TAG}"
echo "[4/4] Done! GitHub Actions will build Docker image and wheel."
echo "Monitor: https://github.com/<user>/praxic/actions"
