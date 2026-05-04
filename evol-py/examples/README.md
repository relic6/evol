# EVOL Examples

Two reference examples that show EVOL working end-to-end:

| Example | What it demonstrates |
|---|---|
| [`journal-cli/`](./journal-cli/) | Standalone CLI using **direct backend** (Anthropic API) — the QUICKSTART scenario |
| [`journal-cli-skill/`](./journal-cli-skill/) | Same product wrapped as a **Claude Code Skill** using the **host backend** — EVOL has no API key of its own; the host agent processes deferred reflection requests |

Both share the same Memory shape and config schema. The only thing that differs is *who calls the LLM*.

## Running

```bash
# From the repo root:
pip install -e ".[dev]"

# Standalone direct backend
cd examples/journal-cli
export ANTHROPIC_API_KEY=...
python journal_cli.py < today.txt

# Run a fully-deterministic 30-day evolution simulation (no API key needed)
python simulate_30_days.py

# Skill version: copy the skill folder into your Claude Code skills dir
# (see journal-cli-skill/SKILL.md for instructions)
```
