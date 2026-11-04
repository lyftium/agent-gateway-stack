#!/usr/bin/env bash
# Copy CI manifests from ci/ into .github/workflows/ once the repo has
# the `workflow` OAuth scope (gh auth refresh -s workflow).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .github/workflows
shopt -s nullglob
copied=0
for f in ci/*.yml ci/*.yaml; do
  base="$(basename "$f")"
  if [[ "$base" == github-actions-ci.yml || "$base" == ci.yml ]]; then
    dest=".github/workflows/ci.yml"
  else
    dest=".github/workflows/$base"
  fi
  cp "$f" "$dest"
  echo "installed $f -> $dest"
  copied=$((copied + 1))
done
if [[ "$copied" -eq 0 ]]; then
  echo "No ci/*.yml found" >&2
  exit 1
fi
echo "Commit and push .github/workflows/ to enable Actions."
