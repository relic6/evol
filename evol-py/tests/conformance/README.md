# EVOL Conformance Test Suite (CTS)

This is the **protocol-level** test suite. Any SDK that claims to be EVOL-conformant **MUST** pass every test in this directory at the protocol version it implements.

CTS is **language-agnostic by intent** — the Python implementation here serves as the reference. Other-language SDKs (`evol-ts`, `evol-java`) are expected to port these tests to their own test framework while preserving the **same assertions**.

## Categories

| File | What it asserts |
|---|---|
| `test_schema.py` | All on-disk artifacts conform to the schemas in DATA-MODEL.md |
| `test_behavior.py` | The 5 product API + 5 admin API behave per CONTRACT §7 / §8 |
| `test_concurrency.py` | Multi-process file lock, atomicity, lock-residual recovery |
| `test_anchor.py` | Anchor enforcement is fail-safe and unbypassable |

## Running

```bash
# All conformance tests
pytest tests/conformance/

# A single category
pytest tests/conformance/test_schema.py -v
```

## Versioning

CTS itself is versioned alongside the protocol. A test that's tagged with
`@pytest.mark.protocol("0.1")` runs only when the SDK declares that version.
For v0.1 every test is implicitly tagged 0.1.

## What "conformant" means

A SDK is **conformant for protocol_version X** when:

1. Every CTS file at version X passes
2. The SDK's manifest writes ``protocol_version: "X"``
3. A `.evol/` directory written by SDK A and read by SDK B (both claiming X) produces identical Memory checksums
