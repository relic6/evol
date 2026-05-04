# journal-cli

A 60-line example showing **EVOL in production** with the direct backend.

## What it does

Pipe a day's journal text in, get a 100-character summary back. Each interaction is recorded; over time the summaries adapt to your style.

## Try it

### With a real LLM (Anthropic)

```bash
export ANTHROPIC_API_KEY=...
python journal_cli.py < today.txt
```

Attach feedback to the most recent run:

```bash
python journal_cli.py --feedback edited
python journal_cli.py --feedback discarded
python journal_cli.py --feedback kept
```

After 5 closed tasks, EVOL automatically triggers a reflection (per `evol.config.yaml`'s `reflection.threshold: 5`). Inspect the result:

```bash
evol --root . status
evol --root . memory show user_profile
ls .evol/insights/
```

### Without an API key — the deterministic 30-day simulation

```bash
python simulate_30_days.py
```

This runs the full lifecycle end-to-end using a mock LLM. You'll see Memory grow from version 0 → ~5 over 30 simulated days, with concrete entries appearing in `.evol/memory/` after each reflection cycle.

## What's interesting

After running the simulation, look at `.evol/`:

```
.evol/
├── manifest.yaml             # current state pointer
├── experiences.jsonl         # 30 task records
├── experiences.feedback.jsonl  # 10 'edited' signals
├── memory/
│   ├── user_profile.yaml     # ~2 entries
│   ├── domain_knowledge.yaml # ~1 entry
│   └── self_awareness.yaml   # ~1 entry
├── insights/                 # one .md per reflection cycle
└── versions/                 # 6 immutable snapshots
```

Every file is human-readable; you can `cat`, `vim`, `git diff` everything.
