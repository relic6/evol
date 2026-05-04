# EVOL

> Where software learns to grow, and so do you.

EVOL is a lightweight, embeddable **growth infrastructure layer** for AI software.
After integrating EVOL, a product can learn from its own usage in a controlled,
explainable, and rollbackable way, then feed that learning back into future
tasks and occasionally surface useful insights to its users.

EVOL is not an agent framework, an execution engine, or a SaaS platform. It is a
local-first SDK plus an interoperable disk protocol centered on the `.evol/`
directory.

[中文 README](./README_CN.md)

## Why EVOL Exists

Most AI products optimize for completing the current task. Once the task is
done, user edits, feedback, preferences, repeated failures, and surprising
successes are usually discarded or hidden in ad hoc logs.

EVOL treats every interaction as both:

- a task to complete now
- an experience to learn from later

The goal is to help products move from static tools toward growth-oriented
companions, while keeping that growth readable, versioned, and reversible.

## Positioning

EVOL sits above execution and agent frameworks. It complements them instead of
replacing them.

```text
Product Code
  ├─ recorder.start_task / end_task / feedback
  ├─ advisor.enhance
  └─ advisor.inspire
        │
        ▼
EVOL Growth Layer
  Recorder · Reflector · Memory · Advisor
        │
        ▼
Execution Layer
  Harness / LangGraph / AutoGen / direct LLM SDK / your own runtime
```

Harness helps a workflow do the right thing reliably. EVOL helps the product do
things better over time.

## What EVOL Provides

| Capability | What it means |
|---|---|
| Experience recording | Append-only logs for meaningful product tasks |
| Feedback signals | `kept`, `edited`, `discarded`, `rated`, `comment`, and custom signals |
| Structured reflection | Batch experiences into auditable insights |
| Long-term memory | Human-readable YAML assets for user profile, domain knowledge, and self-awareness |
| Prompt enhancement | Inject relevant memory into future prompts before the product calls its LLM |
| Inspiration | Occasionally surface thought-provoking observations back to users |
| Versioning and rollback | Snapshot memory changes and restore previous versions |
| Local-first storage | All growth assets live in `.evol/` and can be inspected, diffed, backed up, or redacted |

## Current Implementation

The Python reference implementation lives in [`evol-py/`](./evol-py/).

- Package name: `evol-kit`
- Import name: `evol`
- Protocol version: `0.1`
- Status: `v0.1.0 alpha`
- Verified test suite: `263 passed`

Core APIs:

| API | Purpose |
|---|---|
| `recorder.start_task(input, ...)` | Open an Experience |
| `recorder.end_task(handle, output=...)` | Close an Experience |
| `recorder.feedback(experience_id, signal)` | Attach feedback |
| `advisor.enhance(prompt, task=...)` | Add relevant Memory to a prompt |
| `advisor.inspire(task=...)` | Maybe return a useful user-facing insight |
| `reflector.reflect()` | Distill recent Experiences into Memory |

## Quick Start

Install the Python reference implementation locally:

```bash
cd evol-py
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the deterministic 30-day simulation. It does not require an API key:

```bash
cd examples/journal-cli
python simulate_30_days.py
```

Inspect the generated growth assets:

```bash
cat .evol/memory/user_profile.yaml
cat .evol/memory/domain_knowledge.yaml
cat .evol/memory/self_awareness.yaml
ls .evol/insights/
ls .evol/versions/
```

Use the CLI:

```bash
evol --root . status
evol --root . memory show
evol --root . versions
evol --root . diff 0 1
```

For a fuller walkthrough, read [GETTING-STARTED.md](./GETTING-STARTED.md).

## Minimal Integration

Create `evol.config.yaml` in your product root:

```yaml
schema_version: 1

product:
  name: my-product
  version: 0.1.0
  domain: your product domain

anchors:
  - description: Core product constraint
    kind: text
    rule: The product must not learn behavior that violates this principle.

reflection:
  trigger: threshold
  threshold: 20

inspiration:
  frequency: low
  cooldown_hours: 24
  max_per_day: 2

llm:
  backend: auto
```

Add EVOL to your task loop:

```python
from evol import Evol

evol = Evol.from_config("evol.config.yaml")

def run_task(user_input: str) -> str:
    handle = evol.recorder.start_task(
        input=user_input,
        task_kind="your_task_kind",
    )

    prompt = build_prompt(user_input)
    prompt = evol.advisor.enhance(
        prompt,
        task={"task_kind": "your_task_kind"},
    )

    output = call_your_llm(prompt)
    experience_id = evol.recorder.end_task(handle, output=output)

    return output
```

Record feedback when the user reacts:

```python
from evol.core.time_utils import utc_now_iso
from evol.core.types import Signal

evol.recorder.feedback(
    experience_id,
    Signal(type="edited", ts=utc_now_iso(), source="explicit"),
)
```

Trigger reflection outside the user request path:

```bash
evol reflect
evol memory show
```

## The `.evol/` Directory

EVOL's growth assets are visible on disk:

```text
.evol/
├── manifest.yaml
├── config.yaml
├── experiences.jsonl
├── experiences.feedback.jsonl
├── memory/
│   ├── user_profile.yaml
│   ├── domain_knowledge.yaml
│   └── self_awareness.yaml
├── insights/
├── versions/
└── locks/
```

This is the heart of EVOL's trust model:

- You can read what the product learned.
- You can edit Memory manually.
- You can diff versions.
- You can roll back bad growth.
- You can export a redacted bundle for review or migration.

## LLM Backends

EVOL supports three backend modes:

| Backend | Use when |
|---|---|
| `direct` | Your product owns API keys for Anthropic or OpenAI |
| `subprocess` | You want to reuse a local `claude` or `codex` CLI login |
| `host` | EVOL runs inside a host agent or Skill, and the host performs LLM calls |
| `auto` | You want EVOL to detect the best available backend |

See [LLM-BACKENDS.md](./LLM-BACKENDS.md) for details.

## CLI Overview

```bash
evol init
evol status
evol reflect
evol memory show
evol memory edit user_profile
evol versions
evol diff 0 1
evol rollback 1
evol export ./backup.tgz
evol import ./backup.tgz
evol pause
evol resume
```

## Documentation Map

| Layer | Document |
|---|---|
| Vision | [VISION.md](./VISION.md) |
| Design principles | [PRINCIPLES.md](./PRINCIPLES.md) |
| First runnable tutorial | [GETTING-STARTED.md](./GETTING-STARTED.md) |
| Original integration thought experiment | [QUICKSTART.md](./QUICKSTART.md) |
| Architecture | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Protocol contract | [CONTRACT.md](./CONTRACT.md) |
| Data model | [DATA-MODEL.md](./DATA-MODEL.md) |
| Internal flows | [FLOWS.md](./FLOWS.md) |
| LLM backend design | [LLM-BACKENDS.md](./LLM-BACKENDS.md) |
| Python implementation notes | [IMPLEMENTATION.md](./IMPLEMENTATION.md) |

## Development

```bash
cd evol-py
python -m pip install -e ".[dev]"

ruff check src tests
ruff format src tests
mypy
pytest -q
pytest tests/conformance/ -v
```

## Non-Goals

EVOL deliberately does not:

- modify its own source code
- imitate human consciousness or emotion
- replace execution frameworks or agent runtimes
- require a hosted SaaS service
- hide growth assets in opaque vectors or model weights
- run reflection on every user request

## License

Apache License 2.0. See [LICENSE](./LICENSE).
