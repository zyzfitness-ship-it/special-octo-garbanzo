#!/usr/bin/env python3
"""Reject text carrying lone UTF-16 surrogates.

A lone surrogate (U+D800-U+DFFF with no partner) survives JSON escaping but
cannot be encoded to UTF-8, so it detonates later -- usually inside an API
call, far from wherever it was pasted in. Catching it at the boundary turns a
confusing downstream crash into a clear message.

Reads the hook payload on stdin. Fails OPEN: anything unexpected exits 0
rather than wedging the session.
"""
import json
import sys

SURROGATE_RANGE = range(0xD800, 0xE000)


def walk_strings(node, path="$"):
    """Yield (json_path, text) for every string anywhere in the payload."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_strings(value, f"{path}[{index}]")


def offending_spans(text):
    """Return (index, codepoint) for each surrogate. Python stores code points,
    so any surrogate present in a str is by definition unpaired."""
    return [(i, ord(c)) for i, c in enumerate(text) if ord(c) in SURROGATE_RANGE]


def main():
    event = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else "pretooluse"

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    findings = []
    for path, text in walk_strings(payload):
        for index, codepoint in offending_spans(text):
            findings.append(f"{path} at offset {index}: U+{codepoint:04X}")

    if not findings:
        return 0

    detail = "; ".join(findings[:5])
    if len(findings) > 5:
        detail += f" (+{len(findings) - 5} more)"
    reason = f"Unpaired UTF-16 surrogate found -- this cannot be encoded as UTF-8: {detail}"

    if event.startswith("userpromptsubmit"):
        out = {"decision": "block", "reason": reason}
    else:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
