#!/usr/bin/env bash
# Commit the given files and push, rebasing onto the latest remote first.
# Several workflows commit to this repo (stock checker every 15 min, watchlist
# manager, economic alert, ...). A plain `git push` fails if another run pushed
# in the meantime, so we pull --rebase and retry.
#
# Usage: commit_and_push.sh "commit message" file [file...]
set -euo pipefail

message="$1"; shift

git config user.name  "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# Only stage files that exist (e.g. a state file is not created until first needed).
for f in "$@"; do
  if [ -e "$f" ]; then git add -- "$f"; else echo "Skipping missing file: $f"; fi
done
if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi
git commit -m "$message"

branch="${GITHUB_REF_NAME:-main}"
for attempt in 1 2 3 4 5; do
  if git pull --rebase origin "$branch" && git push origin "HEAD:$branch"; then
    echo "Pushed on attempt $attempt."
    exit 0
  fi
  echo "Push attempt $attempt failed (remote changed or rebase conflict)."
  git rebase --abort 2>/dev/null || true
  sleep $((attempt * 3))
done

echo "::error::Could not push after 5 attempts. Changes were not saved."
exit 1
