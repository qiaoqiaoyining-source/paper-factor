#!/usr/bin/env bash
# Sync latest whzzzz2004-netizen/paper-factor into this fork, then push to origin.
# Usage (from repo root):
#   bash scripts/sync_from_upstream.sh
#   bash scripts/sync_from_upstream.sh --push   # also push to qiaoqiaoyining-source

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
ORIGIN_REMOTE="${ORIGIN_REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
DO_PUSH=0

for arg in "$@"; do
  case "$arg" in
    --push) DO_PUSH=1 ;;
    -h|--help)
      echo "Usage: bash scripts/sync_from_upstream.sh [--push]"
      echo "  Fetches upstream/main and merges into local ${BRANCH}."
      echo "  With --push, pushes ${BRANCH} to origin (${ORIGIN_REMOTE})."
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 1
      ;;
  esac
done

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "Adding upstream remote..."
  git remote add "$UPSTREAM_REMOTE" https://github.com/whzzzz2004-netizen/paper-factor.git
fi

if ! git remote get-url "$ORIGIN_REMOTE" >/dev/null 2>&1; then
  echo "Adding origin remote..."
  git remote add "$ORIGIN_REMOTE" https://github.com/qiaoqiaoyining-source/paper-factor.git
fi

echo "==> Fetching ${UPSTREAM_REMOTE}/${BRANCH}..."
git fetch "$UPSTREAM_REMOTE" "$BRANCH"

echo "==> Merging ${UPSTREAM_REMOTE}/${BRANCH} into local ${BRANCH}..."
git checkout "$BRANCH"
git merge "${UPSTREAM_REMOTE}/${BRANCH}" -m "merge: sync ${UPSTREAM_REMOTE}/${BRANCH}"

echo
echo "Local branch is now:"
git log --oneline -5 --decorate
echo
echo "Ahead/behind origin (if pushed before):"
git rev-list --left-right --count "${ORIGIN_REMOTE}/${BRANCH}...${BRANCH}" 2>/dev/null || echo "  (origin/${BRANCH} not on this machine yet — first push pending)"

if [[ "$DO_PUSH" -eq 1 ]]; then
  echo
  echo "==> Pushing ${BRANCH} to ${ORIGIN_REMOTE}..."
  git push -u "$ORIGIN_REMOTE" "$BRANCH"
  echo "Done. Your fork: https://github.com/qiaoqiaoyining-source/paper-factor"
else
  echo
  echo "Merge complete. To publish your fork:"
  echo "  git push -u ${ORIGIN_REMOTE} ${BRANCH}"
  echo "Or rerun: bash scripts/sync_from_upstream.sh --push"
fi
