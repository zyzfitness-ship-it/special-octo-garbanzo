#!/usr/bin/env bash
# Status line: level, model, directory, git branch, context pressure.
#
# The level marker is the point -- when permissiveness is a setting, you want
# to see which tier is live without opening a config file.
#
# Reads the status payload on stdin. Fails OPEN: prints something, always.

set -uo pipefail

payload="$(cat 2>/dev/null)" || payload=''

field() {
  printf '%s' "$payload" | python3 -c "
import json,sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for key in '$1'.split('.'):
    if not isinstance(d, dict):
        sys.exit(0)
    d = d.get(key)
    if d is None:
        sys.exit(0)
print(d)
" 2>/dev/null
}

model="$(field model.display_name)"
cwd="$(field workspace.current_dir)"
[ -n "$cwd" ] || cwd="$PWD"

branch=''
if command -v git >/dev/null 2>&1; then
  branch="$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null)" || branch=''
fi

level="$(cat "$HOME/.claude/.level" 2>/dev/null)" || level=''

parts=()
[ -n "$level" ]  && parts+=("L${level}")
[ -n "$model" ]  && parts+=("$model")
parts+=("$(basename "$cwd")")
[ -n "$branch" ] && parts+=("⎇ $branch")

printf '%s\n' "$(IFS=' · '; printf '%s' "${parts[*]}")"
