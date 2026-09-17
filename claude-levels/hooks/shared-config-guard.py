#!/usr/bin/env python3
"""Flag writes to files the whole team depends on.

Editing CI config, a lockfile, or settings.json is not dangerous the way
`rm -rf` is -- it is dangerous the way a quiet change to shared state is.
Nothing here blocks. PreToolUse asks for confirmation; PostToolUse records
what landed, so there is a trail when something starts behaving differently.

Runs on both events; distinguishes them by hook_event_name. Reads the hook
payload on stdin. Fails OPEN: anything unexpected exits 0.
"""
import datetime
import json
import os
import re
import sys

SHARED_CONFIG = [
    (re.compile(r"(^|/)\.claude/settings(\.local)?\.json$"), "Claude Code settings"),
    (re.compile(r"(^|/)\.mcp\.json$"), "MCP server config"),
    (re.compile(r"(^|/)CLAUDE\.md$"), "project instructions"),
    (re.compile(r"(^|/)\.github/workflows/"), "CI workflow"),
    (re.compile(r"(^|/)\.github/(CODEOWNERS|dependabot\.yml)$"), "repo governance"),
    (re.compile(r"(^|/)(Dockerfile|docker-compose\.ya?ml)$"), "container build"),
    (re.compile(r"(^|/)(package|tsconfig|pyproject|Cargo)\.(json|toml)$"), "project manifest"),
    (re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|uv\.lock)$"), "dependency lockfile"),
    (re.compile(r"(^|/)(Makefile|justfile)$"), "build entrypoint"),
    (re.compile(r"(^|/)\.gitignore$"), "ignore rules"),
]

LOG_PATH = os.path.expanduser("~/.claude/shared-config-changes.log")


def classify(path):
    for pattern, label in SHARED_CONFIG:
        if pattern.search(path):
            return label
    return None


def target_path(tool_input):
    return tool_input.get("file_path") or tool_input.get("notebook_path") or ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0

    path = target_path(tool_input)
    if not path:
        return 0

    label = classify(path)
    if not label:
        return 0

    event = payload.get("hook_event_name") or (
        "PostToolUse" if "tool_response" in payload else "PreToolUse"
    )

    if event == "PreToolUse":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": (
                    f"{path} is {label} -- shared state that affects everyone on "
                    f"this repo. Confirm this change is intended."
                ),
            }
        }))
        return 0

    # PostToolUse: leave a trail.
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp}\t{payload.get('session_id', '-')}\t{label}\t{path}\n")
    except OSError:
        pass  # a guard that breaks the session is worse than a missing log line

    print(json.dumps({"systemMessage": f"Recorded change to {label}: {path}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
