#!/usr/bin/env bash
# Install a permission level into ~/.claude.
#
#   ./install.sh 2              switch to level 2
#   ./install.sh 4 --dry-run    show what would change
#   ./install.sh --status       report the level currently installed
#
# Your existing settings.json is backed up before anything is overwritten.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
LEVEL_MARKER="$CLAUDE_DIR/.level"

die() { printf 'error: %s\n' "$1" >&2; exit 1; }

if [ "${1:-}" = "--status" ]; then
  if [ -f "$LEVEL_MARKER" ]; then
    printf 'installed level: %s\n' "$(cat "$LEVEL_MARKER")"
  else
    printf 'no level installed (no %s)\n' "$LEVEL_MARKER"
  fi
  [ -f "$SETTINGS" ] && printf 'settings: %s\n' "$SETTINGS"
  exit 0
fi

LEVEL="${1:-}"
DRY_RUN=0
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

case "$LEVEL" in
  1|2|3|4) ;;
  *) die "usage: $0 <1|2|3|4> [--dry-run] | --status" ;;
esac

PROFILE="$SRC/levels/settings.level${LEVEL}.json"
[ -f "$PROFILE" ] || die "missing profile: $PROFILE"

python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$PROFILE" \
  || die "$PROFILE is not valid JSON"

printf 'level %s -> %s\n' "$LEVEL" "$CLAUDE_DIR"
python3 -c "
import json,sys
d = json.load(open(sys.argv[1]))
p = d['permissions']
print('  %s' % d.get('//', ''))
print('  defaultMode=%s allow=%d deny=%d ask=%d'
      % (p['defaultMode'], len(p.get('allow', [])), len(p['deny']), len(p['ask'])))
" "$PROFILE"

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\n(dry run -- nothing written)\n'
  [ -f "$SETTINGS" ] && { printf '\nwould replace:\n'; diff -u "$SETTINGS" "$PROFILE" || true; }
  exit 0
fi

mkdir -p "$CLAUDE_DIR/hooks"

if [ -f "$SETTINGS" ]; then
  BACKUP="$SETTINGS.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  cp "$SETTINGS" "$BACKUP"
  printf '  backed up existing settings -> %s\n' "$BACKUP"
fi

for hook in "$SRC"/hooks/*.py "$SRC"/hooks/*.sh; do
  base="$(basename "$hook")"
  if [ "$base" = "statusline.sh" ]; then
    install -m 0755 "$hook" "$CLAUDE_DIR/statusline.sh"
  else
    install -m 0755 "$hook" "$CLAUDE_DIR/hooks/$base"
  fi
done
printf '  installed %s hook scripts\n' "$(ls -1 "$SRC"/hooks | wc -l | tr -d ' ')"

cp "$PROFILE" "$SETTINGS"
printf '%s\n' "$LEVEL" > "$LEVEL_MARKER"
printf '  wrote %s\n' "$SETTINGS"

printf '\ndone. Open /hooks once (or restart Claude Code) to load the new hooks.\n'
