# evol-kit · Python reference implementation of EVOL

> **EVOL — Where software learns to grow, and so do you.**

`evol-kit` is the Python reference implementation of [EVOL](../), the lightweight, embeddable **growth infrastructure** for AI software. After integrating EVOL, any product acquires a **controlled**, **explainable**, **rollbackable** ability to learn from its own use — and to surface insights back to its user.

[![status](https://img.shields.io/badge/status-v0.1.0_alpha-yellow)]()
[![tests](https://img.shields.io/badge/tests-262_passing-brightgreen)]()
[![protocol](https://img.shields.io/badge/protocol-0.1-blue)]()

## What you get

| API | What it does |
|---|---|
| `recorder.start_task(input, ...)` / `end_task(...)` | Append-only Experience log |
| `recorder.feedback(id, signal)` | Attach kept / edited / discarded / rated / comment signals |
| `advisor.enhance(prompt, task=...)` | Inject relevant Memory into prompts |
| `advisor.inspire(task=...)` | Optionally surface a thought-provoking observation |
| `reflector.reflect()` | Periodically distill experiences into structured Memory |
| `reflector.resume_pending()` | Pick up host-backend-deferred reflections |

## Install

```bash
# Latest local development:
git clone <this-repo>
cd evol-py
pip install -e ".[dev]"

# (Coming) PyPI:
pip install evol-kit
```

## 30-second tour

```python
from evol import Evol

evol = Evol.from_config("evol.config.yaml")

# Three lines into your product's task loop:
handle = evol.recorder.start_task(input=user_prompt, task_kind="summarize")
prompt = evol.advisor.enhance(prompt, task={"task_kind": "summarize"})
# ... your LLM call ...
evol.recorder.end_task(handle, output=output)

# Optional: gentle reflection back to the user
inspiration = evol.advisor.inspire()
if inspiration:
    print(f"💡 {inspiration.text}")
```

The `.evol/` directory next to `evol.config.yaml` holds **everything** — Memory YAMLs, experience JSONL, snapshot tarballs, audit insights — all human-readable, all `git`-able.

## Three LLM backends

Configure once in `evol.config.yaml`:

```yaml
llm:
  backend: auto      # direct | subprocess | host | auto
```

| Backend | When to use |
|---|---|
| `direct` | Standalone tool with its own API key (Anthropic / OpenAI) |
| `subprocess` | Local `claude` or `codex` CLI is available; reuse its credentials |
| `host` | EVOL is loaded as a Skill in Claude Code / Codex — host agent runs the LLM, EVOL just orchestrates Memory |

See [`LLM-BACKENDS.md`](../LLM-BACKENDS.md) for the full design.

## Examples

```bash
cd examples/journal-cli
export ANTHROPIC_API_KEY=...
python journal_cli.py < today.txt          # direct backend
python simulate_30_days.py                  # deterministic, no API key needed
```

For the Claude Code Skill version:

```bash
ls examples/journal-cli-skill/              # SKILL.md + scripts/
```

## CLI

```
evol init       # bootstrap a fresh .evol/
evol status     # show current state
evol reflect    # trigger a reflection cycle
evol memory     # show / edit Memory
evol versions   # list snapshot history
evol rollback N # restore Memory from snapshot N
evol diff A B   # text diff between two snapshots
evol export     # bundle .evol/ as tar.gz (redacted by default)
evol import     # restore from a bundle
evol pause      # freeze growth (still serves enhance reads)
evol resume
```

## Develop

```bash
pip install -e ".[dev]"

# Lint / format / type-check
ruff check src tests && ruff format src tests
mypy

# Tests
pytest -q                                 # unit + integration (215 tests)
pytest tests/conformance/ -v              # protocol CTS (47 tests)
pytest --cov=evol --cov-report=term       # coverage
```

## Project layout

```
evol-py/
├── src/evol/
│   ├── core/         # protocol-level types, ids, time, canonicalization
│   ├── config/       # evol.config.yaml schema + anchor lifecycle
│   ├── concurrency/  # file lock, atomic write, tar snapshots
│   ├── recorder/     # append-only experience log + feedback overlay
│   ├── memory/       # MemoryStore, ManifestStore, SnapshotManager, Consolidator
│   ├── llm/          # 3-backend abstraction + auto-detect
│   ├── reflector/    # state machine: trigger → batcher → prompt → parse → filter → consolidate
│   ├── advisor/      # enhance + inspire (4-gate throttle, host_strategy)
│   ├── api/          # the public Evol facade
│   └── cli/          # click commands
├── tests/
│   ├── unit/         # 158 tests
│   ├── integration/  # 16 tests
│   └── conformance/  # 47 protocol-level tests (any conforming SDK MUST pass)
├── examples/
│   ├── journal-cli/         # direct backend
│   └── journal-cli-skill/   # Claude Code Skill (host backend)
└── pyproject.toml
```

## Documentation

Full design documentation lives one level up in [`evol/`](../):

| Layer | Document |
|---|---|
| Foundation | [VISION](../VISION.md) / [PRINCIPLES](../PRINCIPLES.md) / [QUICKSTART](../QUICKSTART.md) |
| Design (language-agnostic) | [ARCHITECTURE](../ARCHITECTURE.md) / [CONTRACT](../CONTRACT.md) / [DATA-MODEL](../DATA-MODEL.md) / [FLOWS](../FLOWS.md) / [LLM-BACKENDS](../LLM-BACKENDS.md) |
| Implementation (Python) | [IMPLEMENTATION](../IMPLEMENTATION.md) — including the 84-task progress table |

