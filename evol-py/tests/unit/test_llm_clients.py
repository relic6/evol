"""Unit tests for the LLM client abstraction (mock + subprocess + host)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from evol.errors import EvolLLMError, EvolParseError
from evol.llm import (
    DeferredLLMResponse,
    HostAgentClient,
    LLMBackendKind,
    LLMResponse,
    Message,
    MockLLMClient,
    SubprocessLLMClient,
)

# ─── MockLLMClient ───


def test_mock_client_sequential_responses() -> None:
    client = MockLLMClient(["first", "second"])
    r1 = client.chat([Message(role="user", content="?")])
    r2 = client.chat([Message(role="user", content="?")])
    assert r1.text == "first"
    assert r2.text == "second"
    assert r1.backend == LLMBackendKind.DIRECT


def test_mock_client_callable_responses() -> None:
    client = MockLLMClient(lambda msgs, purpose: f"got {len(msgs)} for {purpose}")
    r = client.chat(
        [Message(role="user", content="hi")], purpose="reflection"
    )
    assert r.text == "got 1 for reflection"


def test_mock_client_exhausted_raises() -> None:
    client = MockLLMClient([])
    with pytest.raises(EvolLLMError):
        client.chat([Message(role="user", content="?")])


def test_mock_client_records_calls() -> None:
    client = MockLLMClient(["x"])
    client.chat([Message(role="user", content="abc")], purpose="reflection", temperature=0.1)
    assert len(client.calls) == 1
    assert client.calls[0]["purpose"] == "reflection"
    assert client.calls[0]["temperature"] == 0.1


# ─── SubprocessLLMClient ───


def test_subprocess_runs_command_and_returns_text(tmp_path: Path) -> None:
    """Use a tiny Python subprocess as a stand-in for `claude -p`."""
    helper = tmp_path / "echo.py"
    helper.write_text(
        "import sys\nprint('echoed:', sys.stdin.read().strip()[:30])\n",
        encoding="utf-8",
    )
    client = SubprocessLLMClient(command=[sys.executable, str(helper)])
    resp = client.chat([Message(role="user", content="hello")])
    assert resp.backend == LLMBackendKind.SUBPROCESS
    assert resp.text.startswith("echoed:")


def test_subprocess_json_format(tmp_path: Path) -> None:
    helper = tmp_path / "json_helper.py"
    helper.write_text(
        'import json, sys\n'
        'sys.stdout.write(json.dumps({"text": "from json"}))\n',
        encoding="utf-8",
    )
    client = SubprocessLLMClient(
        command=[sys.executable, str(helper)],
        format="json",
    )
    resp = client.chat([Message(role="user", content="x")])
    assert resp.text == "from json"


def test_subprocess_nonzero_exit_raises(tmp_path: Path) -> None:
    helper = tmp_path / "fail.py"
    helper.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    client = SubprocessLLMClient(command=[sys.executable, str(helper)])
    with pytest.raises(EvolLLMError):
        client.chat([Message(role="user", content="x")])


def test_subprocess_command_not_found() -> None:
    client = SubprocessLLMClient(command=["__definitely_not_a_real_binary__"])
    with pytest.raises(EvolLLMError, match="not found"):
        client.chat([Message(role="user", content="x")])


def test_subprocess_empty_command_rejected() -> None:
    with pytest.raises(EvolLLMError):
        SubprocessLLMClient(command=[])


# ─── HostAgentClient ───


def test_host_client_chat_writes_pending_request(tmp_path: Path) -> None:
    client = HostAgentClient(evol_root=tmp_path, host_name="claude-code")
    resp = client.chat(
        [
            Message(role="system", content="be helpful"),
            Message(role="user", content="reflect please"),
        ],
        purpose="reflection",
    )
    assert isinstance(resp, DeferredLLMResponse)
    assert resp.pending_path.is_file()
    assert resp.purpose == "reflection"

    md = resp.pending_path.read_text(encoding="utf-8")
    assert md.startswith("---\n")
    assert "request_id:" in md
    assert "## System Prompt" in md
    assert "## User Prompt" in md
    assert "be helpful" in md
    assert "reflect please" in md


def test_host_client_poll_returns_none_until_response_ready(tmp_path: Path) -> None:
    client = HostAgentClient(evol_root=tmp_path)
    deferred = client.chat([Message(role="user", content="x")], purpose="reflection")

    assert client.poll(deferred) is None

    # Simulate host writing the answer
    payload = {
        "insights": [
            {
                "scope": "user_profile",
                "key": "tone",
                "claim": "user prefers concise text",
                "proposed_change": {"op": "set", "value": "concise"},
                "confidence": 0.85,
                "evidence_ids": ["exp_001", "exp_002"],
            }
        ],
        "model": "claude-code-internal",
    }
    deferred.expected_response_path.write_text(json.dumps(payload), encoding="utf-8")

    resp = client.poll(deferred)
    assert isinstance(resp, LLMResponse)
    assert resp.backend == LLMBackendKind.HOST
    # Reflection responses are returned as serialized JSON for the parser.
    parsed = json.loads(resp.text)
    assert parsed["insights"][0]["key"] == "tone"


def test_host_client_poll_invalid_json_raises(tmp_path: Path) -> None:
    client = HostAgentClient(evol_root=tmp_path)
    deferred = client.chat([Message(role="user", content="x")], purpose="reflection")
    deferred.expected_response_path.write_text("not json {", encoding="utf-8")
    with pytest.raises(EvolParseError):
        client.poll(deferred)


def test_host_client_unknown_purpose_rejected(tmp_path: Path) -> None:
    client = HostAgentClient(evol_root=tmp_path)
    with pytest.raises(EvolLLMError):
        client.chat([Message(role="user", content="x")], purpose="bogus")


def test_host_client_request_includes_schema_for_purpose(tmp_path: Path) -> None:
    client = HostAgentClient(evol_root=tmp_path)
    for purpose in ("reflection", "inspiration", "anchor_check"):
        d = client.chat([Message(role="user", content="x")], purpose=purpose)
        text = d.pending_path.read_text(encoding="utf-8")
        assert "Expected Response Schema" in text
        # Each purpose has a distinct schema body
        assert "```json" in text
