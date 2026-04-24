# Phase 14 — Tests

## Prerequisites

- [ ] Phase 13 complete, CI is running
- [ ] Verification tests from phase 03 already exist

## Goal

A small, focused test suite covering the highest-risk logic. Not comprehensive — comprehensive testing in 2 days is a losing trade. Target: ~15-20 tests that cover the verification path (where bugs hide) and the agent's tool-call format.

## Context for Claude Code

- **Unit tests**: fast, no AWS calls, no LLM calls. Run on every CI.
- **Integration tests**: hit Bedrock/KB. Marked `@pytest.mark.integration`, skipped in CI, runnable locally.
- Don't test what we don't own (don't test that Bedrock returns valid responses; test that our code handles them correctly)
- Use `pytest-mock` for mocking boto3 clients

## Steps

### 14.1 — Expand `tests/test_verification.py` (most of this is already done in phase 03)

Ensure coverage of:
- Email: 7 cases (3 valid + 4 invalid)
- SSN extraction: 6 cases
- `verify_user` success + failure paths with mocked user data

### 14.2 — New test file: `tests/test_tools.py`

```python
import json
import pytest
from unittest.mock import patch

from ck_agent.tools import TOOL_CONFIG, dispatch_tool, check_order_status


def test_tool_config_shape():
    """Bedrock Converse expects a specific toolConfig shape."""
    assert "tools" in TOOL_CONFIG
    assert len(TOOL_CONFIG["tools"]) == 2
    for t in TOOL_CONFIG["tools"]:
        assert "toolSpec" in t
        assert "name" in t["toolSpec"]
        assert "inputSchema" in t["toolSpec"]
        assert t["toolSpec"]["inputSchema"]["json"]["type"] == "object"


def test_dispatch_unknown_tool_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        dispatch_tool("not_a_tool", {})


def test_check_order_status_rejects_bad_email():
    r = check_order_status(email="not-a-cloudkinetics-email@gmail.com", ssn_last4="1234", dob_iso="1990-01-01")
    # Since verify_user is called, and this email won't be in USERS, it returns verified=False
    assert r["verified"] is False


def test_multi_order_flow_alice():
    """Alice has 3 orders. Without selected_order_id, response should flag multi_orders."""
    # This test depends on Alice's actual SSN/DOB in mock_data — update constants accordingly
    from ck_agent.mock_data import USERS
    alice = USERS["alice@ck1.com"]
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4=alice.ssn_full[-4:],
        dob_iso=alice.dob_iso,
    )
    assert r["verified"] is True
    assert r.get("multiple_orders_found") is True
    assert "orders_summary" in r
    assert len(r["orders_summary"]) == 3


def test_specific_order_selection_alice():
    from ck_agent.mock_data import USERS
    alice = USERS["alice@ck1.com"]
    first_order_id = alice.orders[0].order_id
    r = check_order_status(
        email="alice@ck1.com",
        ssn_last4=alice.ssn_full[-4:],
        dob_iso=alice.dob_iso,
        selected_order_id=first_order_id,
    )
    assert r["verified"] is True
    assert "order" in r
    assert r["order"]["order_id"] == first_order_id


def test_single_order_flow_bob():
    """Bob has 1 order. Should return it directly."""
    from ck_agent.mock_data import USERS
    bob = USERS["bob@ck2.com"]
    r = check_order_status(
        email="bob@ck2.com",
        ssn_last4=bob.ssn_full[-4:],
        dob_iso=bob.dob_iso,
    )
    assert r["verified"] is True
    assert "order" in r


def test_no_orders_carol():
    """Carol has 0 orders."""
    from ck_agent.mock_data import USERS
    carol = USERS["carol@ck123.com"]
    r = check_order_status(
        email="carol@ck123.com",
        ssn_last4=carol.ssn_full[-4:],
        dob_iso=carol.dob_iso,
    )
    assert r["verified"] is True
    assert r["orders"] == []
```

### 14.3 — New test file: `tests/test_session_store.py`

Uses moto (AWS mocking library) to test DDB interactions without a real AWS account.

```python
import pytest
import boto3
from moto import mock_aws

from ck_agent.session_store import (
    get_or_create_session,
    save_message,
    load_messages,
    delete_session,
)


@pytest.fixture
def ddb():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="ck-conversations",
            KeySchema=[
                {"AttributeName": "conversation_id", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "conversation_id", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="ck-sessions",
            KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "connection_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        # Important: session_store module imports tables at import time,
        # so we need to reimport after mock is active
        import importlib
        import ck_agent.session_store as ss
        importlib.reload(ss)
        yield ss


def test_create_session_returns_empty(ddb):
    s = ddb.get_or_create_session("conn-1")
    assert s["messages"] == []
    assert s["conversation_id"]


def test_save_and_load_roundtrip(ddb):
    s = ddb.get_or_create_session("conn-1")
    cid = s["conversation_id"]
    ddb.save_message(cid, 1, {"role": "user", "content": [{"text": "hello"}]})
    ddb.save_message(cid, 2, {"role": "assistant", "content": [{"text": "hi there"}]})
    msgs = ddb.load_messages(cid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_session_persists_across_get(ddb):
    s1 = ddb.get_or_create_session("conn-1")
    s2 = ddb.get_or_create_session("conn-1")
    assert s1["conversation_id"] == s2["conversation_id"]


def test_delete_session(ddb):
    ddb.get_or_create_session("conn-1")
    ddb.delete_session("conn-1")
    # Next get creates a new session
    s = ddb.get_or_create_session("conn-1")
    assert s["messages"] == []
```

Add `moto` to dev dependencies in `pyproject.toml`:
```toml
[project.optional-dependencies]
dev = [
    ...
    "moto>=5.0.0",
]
```

### 14.4 — New test file: `tests/test_agent_stream.py` (lightweight — mock Bedrock)

```python
from unittest.mock import patch, MagicMock
from ck_agent.agent import run_agent_stream


def _mock_stream_response(text_chunks: list[str], include_tool_use: bool = False):
    """Build a fake Bedrock converse_stream response."""
    events = []
    for chunk in text_chunks:
        events.append({"contentBlockDelta": {"delta": {"text": chunk}}})
    events.append({"contentBlockStop": {}})
    events.append({"messageStop": {"stopReason": "end_turn"}})
    return {"stream": iter(events)}


@patch("ck_agent.agent.BEDROCK")
def test_simple_streaming_response(mock_bedrock):
    mock_bedrock.converse_stream.return_value = _mock_stream_response(["Hello", ", ", "world!"])
    messages = [{"role": "user", "content": [{"text": "hi"}]}]
    events = list(run_agent_stream(messages))
    text_deltas = [e for e in events if e["type"] == "text_delta"]
    assert "".join(e["text"] for e in text_deltas) == "Hello, world!"
    assert events[-1] == {"type": "end"}
```

### 14.5 — Add a `conftest.py`

```python
import pytest

def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless -m integration is passed."""
    if config.getoption("-m") and "integration" in config.getoption("-m"):
        return
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(pytest.mark.skip(reason="integration test skipped by default"))
```

And ensure `pyproject.toml` has:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that require live AWS services",
]
```

## Verification (human-runnable)

```bash
# Unit tests pass
pytest tests -v -m "not integration"
# Expected: all green, ~15-20 tests

# Test count
pytest tests --collect-only -q | tail -5
# Expected: "X tests collected" where X >= 15

# Integration tests also pass (optional, costs a few cents)
pytest tests -v -m integration
# Expected: all green
```

## Definition of Done

- [ ] `tests/test_verification.py`: email, SSN, DOB (+ integration-marked LLM tests)
- [ ] `tests/test_tools.py`: tool config shape, dispatch, all 4 mock users covered
- [ ] `tests/test_session_store.py`: mocked DDB, 4 tests
- [ ] `tests/test_agent_stream.py`: streaming loop with mocked Bedrock
- [ ] `conftest.py` skips integration tests by default
- [ ] CI on GitHub runs `pytest -m "not integration"` and passes

## Out of Scope

- ❌ End-to-end tests against deployed WebSocket (could be a nice-to-have; prioritize docs instead)
- ❌ Property-based testing (hypothesis library)
- ❌ Coverage reporting (not useful for an assessment deliverable)
- ❌ Performance / load tests

## Commit Message

```
[phase 14] Focused test suite

- test_verification: email, SSN, DOB (w/ integration markers for LLM calls)
- test_tools: tool config shape + dispatch + multi/single/zero order flows
- test_session_store: DDB roundtrip using moto mocks
- test_agent_stream: streaming generator with mocked Bedrock events
- conftest.py skips integration tests by default
- ~18 tests total, all green in CI
- Reference: plans/14_tests.md
```
