# EVOL v0.1.0 Release Notes

**Date**: 2026-05-04
**Protocol version**: `0.1`
**Status**: alpha — public API stable, behavior subject to refinement based on early feedback

---

## What this is

The first usable release of the EVOL Python reference implementation
(`evol-kit`). Implements **the entire protocol** described in `CONTRACT.md`,
`DATA-MODEL.md`, `FLOWS.md`, and `LLM-BACKENDS.md`.

This release is suitable for:
- Building a **standalone EVOL-powered CLI** (e.g. `journal-cli`)
- Embedding EVOL as a **Claude Code Skill** with the host backend
- Using as a **conformance reference** when porting to TypeScript / Java

It is **not yet** suitable for:
- Production high-throughput services (single-machine, single-process focus)
- Multi-tenant scenarios (single-user assumption baked into Memory shape)
- Workloads requiring < 5ms enhance latency (current target ≤ 50ms)

## Highlights

### A complete growth loop

```
   Recorder → Experience log
       ↓
   Reflector (LLM) → Insight candidates
       ↓
   AnchorFilter (fail-safe)
       ↓
   Consolidator (5 ops + confidence cap by evidence count)
       ↓
   Memory (versioned, snapshot-backed, rollback-able)
       ↓
   Advisor.enhance → injected into next prompt
   Advisor.inspire → optional user-facing observation
```

Every step is logged to a human-readable file in `.evol/`. You can `cat`
or `vim` everything; rollback is a single `evol rollback N`.

### Three LLM backends, one API

```python
from evol import Evol
evol = Evol.from_config("evol.config.yaml")  # backend auto-detected
# evol.advisor.enhance(...)     ← never calls LLM (pure retrieval)
# evol.reflector.reflect()      ← uses configured backend
```

| Backend | What it does |
|---|---|
| `direct` | Anthropic / OpenAI direct API |
| `subprocess` | Pipes prompts to local `claude` / `codex` CLI |
| `host` | Writes deferred markdown requests for the host agent (e.g. Claude Code Skill scenario); EVOL holds no credentials |

### 84 implementation tasks, 5 phases

See [`IMPLEMENTATION.md`](../IMPLEMENTATION.md) §9 for the per-task progress
ledger. Every task in Phases 1–5 is marked `✅` for v0.1.

## Quality bar

```
262 tests passing + 1 skipped (anthropic optional dep)

  Unit              ~158
  Integration        ~16
  Conformance (CTS)   47

Coverage:
  core / config / concurrency  : 88–100%
  recorder / memory / api      : 82–92%
  reflector / advisor          : 78–100%
  llm clients                  : 92–100% (excluding optional providers)
```

The Conformance Test Suite is the **single source of truth** for
"is this implementation conformant?". evol-ts and evol-java will be expected
to port these 47 tests verbatim and pass them.

## Breaking changes

N/A (initial release).

## Known issues

- `croniter` is an optional dep; without it `trigger: scheduled` is a no-op
- `python -m evol.cli.main` emits a `RuntimeWarning`; the installed `evol`
  console-script entrypoint does not
- Tests cleanup under read-only mounts (e.g. some sandboxed CI) may fail
  to remove `.evol/`; run from a writable cwd

## Upgrade path

N/A. Future minor releases (`0.2`, `0.3`) will preserve protocol_version `0.1`
on disk and add features additively.

## Acknowledgments

This release is the result of the EVOL design documents distilled over the
past month and the 84-task implementation roadmap in `IMPLEMENTATION.md` §9.
The Conformance Test Suite is the most important artifact — it makes
"protocol-level standardization" a concrete check, not just an aspiration.

---

## Next milestones (tentative)

- **v0.2** — `evol-ts` (TypeScript SDK), thin-binding strategy first
- **v0.3** — Strategy / Capability evolution layers (FLOWS extension)
- **v1.0** — All three SDKs (py / ts / java) at full native parity, CTS frozen
