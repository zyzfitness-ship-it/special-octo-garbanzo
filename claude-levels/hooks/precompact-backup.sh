#!/usr/bin/env bash
# Snapshot the transcript before compaction discards detail.
#
# Compaction is lossy by design. This keeps the pre-compaction transcript so a
# detail that got summarized away is still recoverable afterwards.
#
# Reads the hook payload on stdin. Fails OPEN: a backup that cannot be written
# must not stop the compaction.

set -uo pipefail

BACKUP_DIR="${CLAUDE_PRECOMPACT_DIR:-$HOME/.claude/precompact-backups}"
RETENTION=${CLAUDE_PRECOMPACT_RETENTION:-20}

payload="$(cat)" || exit 0

read_field() {
  printf '%s' "$payload" | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('$1','') or '')
except Exception:
    print('')
" 2>/dev/null
}

transcript="$(read_field transcript_path)"
session="$(read_field session_id)"
trigger="$(read_field trigger)"

[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

mkdir -p "$BACKUP_DIR" 2>/dev/null || exit 0

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$BACKUP_DIR/${stamp}-${trigger:-unknown}-${session:-nosession}.jsonl"

cp "$transcript" "$dest" 2>/dev/null || exit 0

# Keep the newest $RETENTION backups; drop the rest.
ls -1t "$BACKUP_DIR"/*.jsonl 2>/dev/null | tail -n "+$((RETENTION + 1))" \
  | while IFS= read -r stale; do rm -f -- "$stale"; done

printf '{"systemMessage":"Transcript backed up to %s"}\n' "$dest"
exit 0
