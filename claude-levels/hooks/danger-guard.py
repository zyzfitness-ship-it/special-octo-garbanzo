#!/usr/bin/env python3
"""Semantic guard for destructive commands and secret files.

The settings.json deny list is a prefix matcher: `Bash(rm -rf:*)` stops
`rm -rf x` and nothing else -- not `rm -fr x`, not `rm -r -f x`, not
`cd /tmp && rm -rf x`. It also only covers the tool it names, so a
`Read(**/.env)` deny does nothing about `cat .env`.

This hook is where the actual rules live. The deny list stays as a cheap
first pass; this catches what prefix matching cannot express.

Reads the hook payload on stdin. Fails OPEN: anything unexpected exits 0
rather than wedging the session.
"""
import json
import re
import shlex
import sys

# Paths that should never be read, edited, or catted, by any tool.
SECRET_PATTERNS = [
    re.compile(p)
    for p in (
        r"(^|/)\.env($|\.)",
        r"(^|/)\.aws/",
        r"(^|/)\.ssh/",
        r"(^|/)id_(rsa|dsa|ecdsa|ed25519)($|\.)",
        r"(^|/)[^/]*credentials[^/]*\.json$",
        r"(^|/)token\.json$",
        r"(^|/)\.netrc$",
        r"(^|/)\.npmrc$",
        r"(^|/)\.pypirc$",
        r"\.pem$",
        r"\.p12$",
        r"(^|/)service[-_]account.*\.json$",
    )
]

# Commands that read file contents -- these turn a path into an exfiltration.
READERS = {
    "cat", "less", "more", "head", "tail", "strings", "xxd", "od", "hexdump",
    "base64", "cp", "scp", "rsync", "nl", "tac", "bat",
}

# (regex, explanation) over the raw command text.
DANGEROUS = [
    (r"\brm\b(?=(?:\s+-\S+)*\s+-\S*r)(?=(?:\s+-\S+)*\s+-\S*f)",
     "recursive force-remove (rm -rf, in any flag order)"),
    (r"\brm\b\s+(-\S+\s+)*/(?:\s|$)", "rm targeting /"),
    (r"\bmkfs(\.\w+)?\b", "filesystem format"),
    (r"\bdd\b.*\bof=/dev/", "dd writing to a block device"),
    (r"\bchmod\b\s+(-\S+\s+)*777\b", "world-writable chmod"),
    (r"\bchmod\b\s+-R\b", "recursive chmod"),
    (r":\(\)\s*\{.*\}\s*;\s*:", "fork bomb"),
    (r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b",
     "piping a network download straight into a shell"),
    (r"\bsudo\b\s+(shutdown|reboot|halt|poweroff)\b", "host power control"),
    (r"\bpkill\b\s+-f\b", "pkill by full command match"),
    (r"\bkillall\b", "killall"),
    (r"\bgit\b.*\bpush\b.*(--force(?!-with-lease)|(?<![-\w])-f(?![\w-]))",
     "force push (use --force-with-lease)"),
    (r"\bgit\b.*\breset\b.*--hard\b", "git reset --hard discards working tree"),
    (r"\bgit\b.*\bclean\b.*-\S*[xd]", "git clean removes untracked/ignored files"),
    (r"\bfind\b.*-delete\b", "find -delete"),
    (r"\bfind\b.*-exec\s+rm\b", "find -exec rm"),
    (r"\btruncate\b\s+-s\s*0", "truncate to zero"),
    (r">\s*/dev/sd[a-z]", "write to a raw disk"),
]


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


def is_secret(path):
    return any(p.search(path) for p in SECRET_PATTERNS)


def check_bash(command):
    for pattern, explanation in DANGEROUS:
        if re.search(pattern, command):
            return f"Blocked by danger-guard: {explanation}. Command: {command[:200]}"

    # A reader command pointed at a secret path is the `cat .env` hole that
    # Read(**/.env) leaves wide open.
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    saw_reader = False
    for token in tokens:
        bare = token.rsplit("/", 1)[-1]
        if bare in READERS:
            saw_reader = True
            continue
        if saw_reader and is_secret(token):
            return (f"Blocked by danger-guard: reading a credential file via shell "
                    f"({token}). The Read(...) deny rules do not cover Bash.")
    return None


def check_file_tool(tool_input):
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if path and is_secret(path):
        return f"Blocked by danger-guard: {path} looks like a credential file."
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    if tool == "Bash":
        reason = check_bash(tool_input.get("command", "") or "")
    else:
        reason = check_file_tool(tool_input)

    if reason:
        return deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
