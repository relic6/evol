# Changelog

All notable changes to `evol-kit` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] · 2026-05-04 (alpha)

The first usable release of the EVOL Python reference implementation.
Implements protocol_version `0.1` end-to-end.

### Added

#### Core protocol layer (Phase 1)
- `evol.core.types` — pydantic models for the 5 core abstractions
  (Experience / Signal / Insight / Memory / Anchor) plus DeferredState
- `evol.core.canonical` — canonical YAML / JSONL serialization +
  cross-SDK Memory checksum (sha256 over a fixed kind ordering)
- `evol.core.ids` — experience / reflection / insight / deferred-request id generators
- `evol.core.time_utils` — UTC ISO-8601 with millisecond precision
- `evol.config` — pydantic schema for `evol.config.yaml` + anchor lifecycle
  (rule_hash + drift detection)
- `evol.concurrency` — portalocker-based file lock + atomic write-then-rename
  + tar snapshot helpers
- `evol.errors` — 8-class exception hierarchy
- `evol.logging` — structured JSON logging with PII-isolated extras

#### Recorder + Memory + storage (Phase 2)
- `evol.recorder.JsonlStore` — append-only JSONL with advisory file lock
- `evol.recorder.Recorder` — start_task / end_task / feedback (with overlay
  pattern preserving append-only main log) + orphan detection
- `evol.memory.MemoryStore` — canonical YAML read/write with checksum drop
- `evol.memory.ManifestStore` — manifest.yaml R/W with focused mutators
- `evol.memory.SnapshotManager` — create / list / rollback / prune
  (immutable snapshots; rollback never deletes history)
- `evol.api.Evol` — top-level facade with bootstrap, checksum validation,
  anchor drift detection (auto-snapshots on drift)
- CLI: `evol init / status / pause / resume / versions`

#### Reflector + LLM backends (Phase 3)
- `evol.llm.LLMClient` — three-backend abstraction
  (`LLMResponse | DeferredLLMResponse`)
- `evol.llm.AnthropicClient` (direct, default), `OpenAIClient` (optional dep),
  `MockLLMClient` (test-only), `SubprocessLLMClient`,
  `HostAgentClient` (deferred RPC via markdown protocol)
- `evol.llm.detect_backend` — 5-level priority auto-detection
  (EVOL_BACKEND > EVOL_HOST_AGENT > API keys > local CLI > error)
- `evol.reflector` — full state machine: trigger → batcher → prompt builder
  → LLM call → parser → anchor filter → consolidator → snapshot →
  insights/*.md
- `evol.reflector.Reflector.resume_pending` — picks up host-completed
  responses on the next session boot
- `evol.memory.Consolidator` — 5 ops (set / merge / strengthen / weaken /
  retire) with per-evidence-count confidence cap
- CLI: `evol reflect [--pickup-only]`

#### Advisor + inspirations (Phase 4)
- `evol.advisor.Advisor` — never-throwing `enhance()` and `inspire()`
- `evol.advisor.Retrieval` — keyword + tag + recency scoring
  (no vector DB; bidirectional fragment matching)
- `evol.advisor.BudgetManager` — per-call advice token budget
- `evol.advisor.InspirationHistory` — append-only history for
  cooldown / daily-quota gating
- 4-gate inspiration throttling (frequency / cooldown / daily quota / warmup)
  with deterministic PRNG coin flip
- `inspiration.host_strategy` — three modes: `defer` (write pending),
  `template` (no-LLM Memory snapshot fill), `disabled`
- CLI: `evol memory show / edit`, `evol rollback`, `evol diff`,
  `evol export --redacted | --full`, `evol import`

#### Reference examples + Conformance Test Suite (Phase 5)
- `examples/journal-cli/` — direct backend, runs against Anthropic
- `examples/journal-cli/simulate_30_days.py` — fully deterministic
  no-API-key 30-day evolution simulation
- `examples/journal-cli-skill/` — Claude Code Skill wrapper using host backend
- `tests/conformance/` — 47-test protocol-level CTS:
  - `test_schema.py` — canonicalization byte stability + on-disk schemas
  - `test_behavior.py` — 5-API behavior contracts including never-raise
  - `test_concurrency.py` — file lock serialization + crash recovery
  - `test_anchor.py` — anchor unbypassability + audit trail

### Quality bar
- 215 unit + integration tests, 47 CTS tests, all passing
- Phase implementation modules at 70–100% line coverage
- end-to-end CLI smoke verified for all phases
- 30-day simulation produces a realistic Memory growth trajectory
- Cross-SDK checksum determinism enforced by canonicalization tests

### Known limitations
- `croniter` is an optional dependency; without it, `trigger: scheduled` is a no-op (use manual or threshold)
- `evol.cli.main:main` warns about `RuntimeWarning` when invoked via `python -m evol.cli.main`; the installed `evol` console-script entry point does not exhibit this
- `tests/integration/` paths under read-only mounts may need a writable cwd to clean up
