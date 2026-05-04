---
name: journal-cli-skill
description: Daily journal summarization with EVOL-powered growth — adapts to your style over time. Loaded as a Claude Code Skill, the host agent (Claude Code) handles the LLM calls; EVOL only orchestrates Memory and reflection.
---

# journal-cli-skill

A reference Skill that wraps the [`journal-cli`](../journal-cli/) example
for use **inside Claude Code** (or any host agent that supports skills).

## How it works

```
┌──────────────────────────────────────────────────────────────┐
│  Claude Code (the host agent)                                │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ skill: journal-cli-skill                               │  │
│  │ ───────────────────────────────────────────────────────│  │
│  │ from evol import Evol                                  │  │
│  │ evol = Evol.from_config("evol.config.yaml")            │  │
│  │ # backend auto-detected as 'host' via EVOL_HOST_AGENT  │  │
│  │                                                        │  │
│  │ enhanced = evol.advisor.enhance(prompt, ...)           │  │
│  │ # ↑ this returns prompt + injected Memory advice       │  │
│  │                                                        │  │
│  │ # The skill returns 'enhanced' — Claude Code then runs │  │
│  │ # its own LLM with that prompt. EVOL never calls a model.│ │
│  │                                                        │  │
│  │ evol.recorder.end_task(handle, claude_code_response)   │  │
│  │ result = evol.reflector.reflect()                      │  │
│  │ # → result.status == "pending_host"                    │  │
│  │ # → .evol/pending_requests/req_xxx.md created          │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

## When you (Claude Code) see pending requests

If you notice files in `.evol/pending_requests/`, you can either:

1. **Wait for the user**: process them when the user explicitly asks
   ("process EVOL pending reflections" or runs `/evol-reflect`).
2. **Ask first**: tell the user "EVOL has a pending reflection request,
   would you like me to handle it now?" and wait for confirmation.
3. **Be proactive on small batches**: for a single pending request from
   today, it's usually fine to ask once and then process.

The pending request file (`req_<ts>_reflection.md`) is structured to be
read directly by you. It contains:
  - the system prompt
  - the user prompt (Memory snapshot + recent experiences)
  - an **Expected Response Schema** section telling you what JSON shape to write back
  - the destination path (`.evol/completed_responses/req_<id>.json`)

After writing the JSON response, EVOL's `resume_pending()` (called on the
next `Evol.from_config(...)`) will pick it up and update Memory.

## Manual triggers

The user can run these commands inside their terminal session:

```bash
# Process all pending EVOL reflections now
python -m evol.cli.main reflect --pickup-only

# Show current Memory
python -m evol.cli.main memory show

# Status
python -m evol.cli.main status
```

## Setup

1. Drop this directory into your Claude Code skills folder (e.g. `.claude/skills/journal-cli-skill/`).
2. Make sure `evol-kit` is installed in the same Python environment your skill scripts use:
   ```bash
   pip install evol-kit
   ```
3. Set the host marker so EVOL auto-selects the host backend:
   ```bash
   export EVOL_HOST_AGENT=claude-code
   ```

## Files

- `evol.config.yaml` — config for the skill (host backend explicitly set).
- `scripts/journal_summarize.py` — the actual entry point invoked by the skill.

## Behavioral promise

When this skill is loaded, EVOL:
- Records every interaction as an Experience (`.evol/experiences.jsonl`)
- Injects Memory into prompts via `enhance()` — **no LLM call made by EVOL**
- Defers reflections to the host (you) via `pending_requests/` markdown
- Never bypasses anchors declared in `evol.config.yaml`
- Survives session boundaries — your processed responses get picked up next session

The user's Memory grows alongside their conversation with you, day by day.
