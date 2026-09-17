#!/usr/bin/env python3
"""Emit settings.level1-4.json from one definition.

The ladder only ever changes two things: defaultMode, and how much is
pre-approved. The deny list, the ask list, and the hooks are invariant --
generating them from a shared base is what guarantees that, instead of
trusting four hand-edited copies to stay in sync.

    python3 generate-levels.py        # write levels/
    python3 generate-levels.py --check # verify committed files match
"""
import json
import pathlib
import sys

HOOK = "$HOME/.claude/hooks"

# --- invariant across every level -------------------------------------------

DENY = [
    "Bash(rm -rf:*)",
    "Bash(/bin/rm:*)",
    "Bash(command rm:*)",
    "Bash(sudo rm:*)",
    "Bash(sudo shutdown:*)",
    "Bash(sudo reboot:*)",
    "Bash(mkfs:*)",
    "Bash(dd if=:*)",
    "Bash(chmod -R 777:*)",
    # NOTE: "Bash(git push --force:*)" is deliberately absent. Prefix matching
    # cannot tell --force from --force-with-lease, so that rule also blocked the
    # safe alternative. danger-guard.py draws the distinction semantically.
    "Bash(git push -f:*)",
    "Bash(git reset --hard:*)",
    "Bash(pkill -f:*)",
    "Read(**/.env)",
    "Read(**/.env.*)",
    "Read(**/*credentials*.json)",
    "Read(**/token.json)",
    "Read(**/id_rsa)",
    "Read(**/.aws/**)",
    "Read(**/.ssh/**)",
]

# Outward-facing or irreversible. Stays gated at every level, level 4 included.
ASK = [
    "Bash(git push:*)",
    "Bash(npm publish:*)",
    "Bash(gh repo create:*)",
]


def cmd(script, *args):
    quoted = " ".join(args)
    return f'"{HOOK}/{script}"' + (f" {quoted}" if quoted else "")


def py(script, *args):
    return f'python3 "{HOOK}/{script}"' + (f" {' '.join(args)}" if args else "")


HOOKS = {
    "UserPromptSubmit": [
        {"matcher": "", "hooks": [
            {"type": "command",
             "command": py("check-unpaired-surrogates.py", "--userpromptsubmit"),
             "timeout": 5}]}
    ],
    "PreToolUse": [
        {"matcher": "", "hooks": [
            {"type": "command",
             "command": py("check-unpaired-surrogates.py", "--pretooluse"),
             "timeout": 5}]},
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": py("danger-guard.py"), "timeout": 10}]},
        {"matcher": "Read|Edit|Write|NotebookEdit", "hooks": [
            {"type": "command", "command": py("danger-guard.py"), "timeout": 10}]},
        {"matcher": "Edit|Write|NotebookEdit", "hooks": [
            {"type": "command", "command": py("shared-config-guard.py"), "timeout": 10}]},
    ],
    "PostToolUse": [
        {"matcher": "Edit|Write|NotebookEdit", "hooks": [
            {"type": "command", "command": py("shared-config-guard.py"), "timeout": 10}]}
    ],
    "PreCompact": [
        {"matcher": "manual", "hooks": [
            {"type": "command", "command": cmd("precompact-backup.sh"), "timeout": 30}]},
        {"matcher": "auto", "hooks": [
            {"type": "command", "command": cmd("precompact-backup.sh"), "timeout": 30}]},
    ],
}

STATUS_LINE = {
    "type": "command",
    "command": '"$HOME/.claude/statusline.sh"',
    "padding": 0,
}

# --- what actually varies ----------------------------------------------------

INSPECT = [
    "Read", "Glob", "Grep",
    "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
    "Bash(git show:*)", "Bash(git branch:*)", "Bash(git remote:*)",
    "Bash(ls:*)", "Bash(pwd)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
    "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)", "Bash(wc:*)", "Bash(sed -n:*)",
    "Bash(which:*)", "Bash(file:*)", "Bash(tree:*)", "Bash(du:*)", "Bash(df:*)",
    "Bash(echo:*)", "Bash(date:*)", "Bash(jq:*)", "Bash(diff:*)",
]

BUILD = [
    "Edit", "Write",
    "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(npm run lint:*)",
    "Bash(npm run build:*)", "Bash(npm run format:*)", "Bash(npm run typecheck:*)",
    "Bash(pytest:*)", "Bash(python3 -m pytest:*)", "Bash(python3 -m unittest:*)",
    "Bash(ruff:*)", "Bash(black:*)", "Bash(mypy:*)",
    "Bash(prettier:*)", "Bash(eslint:*)", "Bash(tsc:*)",
    "Bash(cargo build:*)", "Bash(cargo test:*)", "Bash(cargo clippy:*)", "Bash(cargo fmt:*)",
    "Bash(go build:*)", "Bash(go test:*)", "Bash(go vet:*)", "Bash(gofmt:*)",
    "Bash(make:*)",
    "Bash(git add:*)", "Bash(git commit:*)", "Bash(git checkout:*)",
    "Bash(git switch:*)", "Bash(git stash:*)", "Bash(git fetch:*)",
    "Bash(git pull:*)", "Bash(git merge:*)", "Bash(git rebase:*)", "Bash(git restore:*)",
]

PROVISION = [
    "Bash(npm install:*)", "Bash(npm ci:*)", "Bash(pnpm:*)", "Bash(yarn:*)",
    "Bash(pip install:*)", "Bash(pip3 install:*)", "Bash(uv:*)", "Bash(poetry:*)",
    "Bash(cargo add:*)", "Bash(go mod:*)",
    "Bash(docker build:*)", "Bash(docker compose:*)",
    "Bash(npm run dev:*)", "Bash(npm start:*)",
    "Bash(mkdir:*)", "Bash(touch:*)", "Bash(mv:*)", "Bash(cp:*)", "Bash(chmod +x:*)",
]

LEVELS = {
    1: {
        "name": "Guarded",
        "summary": "Every action prompts. Nothing is pre-approved.",
        "defaultMode": "default",
        "allow": [],
    },
    2: {
        "name": "Assisted",
        "summary": "Reading and inspection are free; anything that writes still prompts.",
        "defaultMode": "default",
        "allow": INSPECT,
    },
    3: {
        "name": "Flow",
        "summary": "Edits auto-accept; build, test, lint and local git are pre-approved.",
        "defaultMode": "acceptEdits",
        "allow": INSPECT + BUILD,
    },
    4: {
        "name": "Autonomous",
        "summary": "Auto mode. Dependencies and containers too. Deny list and hooks unchanged.",
        "defaultMode": "auto",
        "allow": INSPECT + BUILD + PROVISION,
    },
}


def build(level):
    spec = LEVELS[level]
    permissions = {}
    if spec["allow"]:
        permissions["allow"] = spec["allow"]
    permissions["deny"] = DENY
    permissions["ask"] = ASK
    permissions["defaultMode"] = spec["defaultMode"]

    settings = {
        "//": f"Level {level} -- {spec['name']}. {spec['summary']}",
        "permissions": permissions,
        "hooks": HOOKS,
        "statusLine": STATUS_LINE,
    }

    # At level 4 the classifier is the thing standing between the agent and the
    # machine, so it gets told explicitly what intent must never clear.
    if level == 4:
        settings["autoMode"] = {
            "hard_deny": [
                "$defaults",
                "Reading, copying or printing credential files (.env, .ssh, .aws, *.pem, service accounts)",
                "Rewriting published git history on a branch someone else may have checked out",
                "Disabling, skipping or deleting tests to make a check pass",
                "Weakening the guards in .claude/hooks or the deny list in settings.json",
            ],
            "soft_deny": [
                "$defaults",
                "Installing dependencies not named in a manifest already in the repo",
            ],
        }
    return settings


def main():
    out_dir = pathlib.Path(__file__).parent / "levels"
    out_dir.mkdir(exist_ok=True)
    check = "--check" in sys.argv
    failures = []

    for level in sorted(LEVELS):
        path = out_dir / f"settings.level{level}.json"
        text = json.dumps(build(level), indent=2) + "\n"
        if check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            status = "ok" if current == text else "STALE"
            if status == "STALE":
                failures.append(path.name)
            print(f"  {path.name}: {status}")
        else:
            path.write_text(text, encoding="utf-8")
            allow = len(LEVELS[level]["allow"])
            print(f"  wrote {path.name}  mode={LEVELS[level]['defaultMode']:<12} "
                  f"allow={allow:<3} deny={len(DENY)} ask={len(ASK)}")

    if failures:
        print(f"\nstale: {', '.join(failures)} -- run without --check", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
