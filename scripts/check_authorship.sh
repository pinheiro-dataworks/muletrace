#!/usr/bin/env bash
# Fail if any commit in a range carries an AI attribution line.
#
# Usage: scripts/check_authorship.sh [<git-range>]
# Without a range, every commit reachable from HEAD is checked. The patterns
# mirror .githooks/commit-msg so that commits made on other machines, where the
# hook may not be active, are caught in CI.
set -euo pipefail

range="${1:-HEAD}"
pattern='^co-authored-by:|generated with \[?claude|claude\.ai/code|noreply@anthropic\.com'

offenders="$(git log --format='%H' "$range" | while read -r sha; do
  if git log -1 --format='%B%n%an <%ae>%n%cn <%ce>' "$sha" | grep -Eiq "$pattern"; then
    echo "$sha"
  fi
done)"

if [[ -n "$offenders" ]]; then
  echo "AI attribution found in these commits:" >&2
  echo "$offenders" >&2
  exit 1
fi
echo "Authorship check passed for range: $range"
