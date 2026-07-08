#!/usr/bin/env bash
# One-time per clone: point git at the versioned .githooks/ dir and make the
# hooks executable. core.hooksPath is a LOCAL config (not shared by clone), so
# each fresh clone must run this once; the hook scripts themselves are committed.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .githooks/post-commit scripts/bump-readiness-stamp.sh 2>/dev/null || true
echo "core.hooksPath → .githooks (this clone). COMPOSE readiness hooks active:"
echo "  pre-commit  : auto-stamp the index 'Updated:' line when the index is committed"
echo "  post-commit : remind to bump the index when compose progress changed without it"
