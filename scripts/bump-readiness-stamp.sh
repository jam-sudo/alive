#!/usr/bin/env bash
# Manually refresh the COMPOSE readiness index "Updated:" stamp (date @ HEAD sha,
# branch) and stage it. Same stamp logic as the pre-commit hook, for ad-hoc use
# after you edit a status row. You still write the row change yourself; this only
# fixes the freshness stamp. Then `git commit` (or fold into your next commit).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
INDEX="docs/superpowers/COMPOSE-SEAL-READINESS.md"
[ -f "$INDEX" ] || { echo "error: $INDEX not found" >&2; exit 1; }

sha="$(git rev-parse --short HEAD)"
branch="$(git rev-parse --abbrev-ref HEAD)"
today="$(date +%Y-%m-%d)"
new_line="> **Updated:** ${today} @ \`${sha}\` (branch \`${branch}\`)"

tmp="$(mktemp)"
awk -v repl="$new_line" '/^> \*\*Updated:\*\*/ { print repl; next } { print }' \
    "$INDEX" > "$tmp" && mv "$tmp" "$INDEX"
git add "$INDEX"
echo "stamped + staged: $new_line"
