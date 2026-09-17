# claude-levels

Four permission profiles for Claude Code, from "ask me everything" to
"go ahead", installed one at a time into `~/.claude`.

```bash
./install.sh 2              # switch to level 2
./install.sh 4 --dry-run    # preview without writing
./install.sh --status       # which level is live
```

Open `/hooks` once (or restart Claude Code) afterwards so the new hooks load.

## The ladder

| Level | Name | `defaultMode` | Pre-approved | What it feels like |
|---|---|---|---|---|
| 1 | Guarded | `default` | nothing | Every action prompts. |
| 2 | Assisted | `default` | 28 rules — reading, searching, `git status/log/diff` | Looking around is free; anything that writes prompts. |
| 3 | Flow | `acceptEdits` | 64 rules — adds build, test, lint, format, local git | Edits land without asking; the test loop runs uninterrupted. |
| 4 | Autonomous | `auto` | 83 rules — adds dependency installs, containers, dev servers | Claude works; the classifier and hooks are the boundary. |

### What never changes

The point of the ladder is that **only convenience scales**. These are byte-identical
across all four files, and `generate-levels.py` is what guarantees it:

- **the deny list** (19 rules)
- **the ask list** — `git push`, `npm publish`, `gh repo create`. Outward-facing
  actions confirm at level 4 exactly as they do at level 1.
- **all six hooks**
- **the status line**

Raising your level buys fewer prompts. It never buys a wider blast radius.

## Layout

```
generate-levels.py     single source of truth -> levels/*.json
levels/                the four generated profiles (committed)
hooks/                 the five hook scripts install.sh deploys
install.sh             installer + backup
test-hooks.sh          31 assertions over the hooks
```

Edit `generate-levels.py`, never `levels/*.json` by hand. `python3 generate-levels.py --check`
fails if the committed files have drifted.

## The hooks

| Script | Runs on | Does |
|---|---|---|
| `check-unpaired-surrogates.py` | `UserPromptSubmit`, every `PreToolUse` | Blocks text carrying lone UTF-16 surrogates before it detonates inside an API call. |
| `danger-guard.py` | `PreToolUse` on `Bash` and file tools | The real guard. Semantic destructive-command and credential-access blocking. |
| `shared-config-guard.py` | `Pre`/`PostToolUse` on writes | Asks before editing CI config, lockfiles, manifests; logs what landed. |
| `precompact-backup.sh` | `PreCompact` | Snapshots the transcript before compaction discards detail. Keeps 20. |
| `statusline.sh` | status line | Shows the live level, model, directory, branch. |

Every hook **fails open** — malformed input exits 0 rather than wedging the
session. That is deliberate, and the reason is in the next section.

## Why the deny list isn't the security boundary

`permissions.deny` is a **prefix matcher**. `Bash(rm -rf:*)` stops `rm -rf x`
and nothing else:

```
rm -fr build          # different flag order   -> not matched
rm -r -f build        # split flags            -> not matched
cd /tmp && rm -rf x   # not at position 0      -> not matched
find . -delete        # never says "rm"        -> not matched
```

It is also scoped per tool, so `Read(**/.env)` does nothing about `cat .env`.

`danger-guard.py` is where the actual rules live; the deny list stays as a cheap
first pass. `test-hooks.sh` asserts every bypass above is caught.

One consequence worth knowing: `Bash(git push --force:*)` is **deliberately absent**
from the deny list. Prefix matching cannot distinguish `--force` from
`--force-with-lease`, so that rule blocked the safe alternative it implicitly
recommends. `danger-guard.py` draws the line semantically — `--force` and `-f`
are blocked, `--force-with-lease` passes.

## A note on hook paths

Hooks here use the **shell form** (a single `command` string), not the exec form
(`command` + `args`). With `args` present, Claude Code spawns the executable
directly with **no shell** — so `~` is never expanded and is passed through as a
literal path segment:

```
python3: can't open file '/your/cwd/~/.claude/hooks/danger-guard.py'
```

`python3` exits **2** for a missing script, and 2 is the hook protocol's
*blocking error* code. A catch-all `PreToolUse` hook in that state returns a
blocking error on every tool call — the session jams rather than degrades.

Use `$HOME` in shell form, or absolute paths in exec form. Never a bare `~` in `args`.

## Testing

```bash
./test-hooks.sh              # 31 assertions, pipes each hook its real payload
python3 generate-levels.py --check
```
