from unittest.mock import patch, MagicMock

from ck_agent.agent import run_agent_stream


def _make_stream(*events):
    """Wrap a list of event dicts into a fake converse_stream response."""
    return {"stream": iter(events)}


def _text_stream(*chunks):
    """Build a simple end_turn stream from text chunks."""
    events = []
    for chunk in chunks:
        events.append({"contentBlockDelta": {"delta": {"text": chunk}}})
    events.append({"contentBlockStop": {}})
    events.append({"messageStop": {"stopReason": "end_turn"}})
    return _make_stream(*events)


# ---------------------------------------------------------------------------
# Basic streaming
# ---------------------------------------------------------------------------

@patch("ck_agent.agent.BEDROCK")
def test_simple_text_stream(mock_bedrock):
    mock_bedrock.converse_stream.return_value = _text_stream("Hello", ", ", "world!")
    messages = [{"role": "user", "content": [{"text": "hi"}]}]

    events = list(run_agent_stream(messages))

    text_deltas = [e for e in events if e["type"] == "text_delta"]
    assert "".join(e["text"] for e in text_deltas) == "Hello, world!"
    assert events[-1] == {"type": "end"}


@patch("ck_agent.agent.BEDROCK")
def test_end_event_always_emitted(mock_bedrock):
    mock_bedrock.converse_stream.return_value = _text_stream("Done.")
    messages = [{"role": "user", "content": [{"text": "go"}]}]

    events = list(run_agent_stream(messages))
    assert any(e["type"] == "end" for e in events)


@patch("ck_agent.agent.BEDROCK")
def test_messages_list_updated_after_stream(mock_bedrock):
    mock_bedrock.converse_stream.return_value = _text_stream("response text")
    messages = [{"role": "user", "content": [{"text": "hello"}]}]

    list(run_agent_stream(messages))

    # Assistant message should have been appended
    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Tool use
# ---------------------------------------------------------------------------

@patch("ck_agent.agent.dispatch_tool")
@patch("ck_agent.agent.BEDROCK")
def test_tool_use_start_event_emitted(mock_bedrock, mock_dispatch):
    mock_dispatch.return_value = "tool result"

    tool_call_stream = _make_stream(
        {"contentBlockStart": {"start": {"toolUse": {"toolUseId": "t1", "name": "retrieve_knowledge"}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"query":"test"}'}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "tool_use"}},
    )
    end_stream = _text_stream("Here is the answer.")
    mock_bedrock.converse_stream.side_effect = [tool_call_stream, end_stream]

    messages = [{"role": "user", "content": [{"text": "what is policy?"}]}]
    events = list(run_agent_stream(messages))

    tool_hints = [e for e in events if e["type"] == "tool_use_start"]
    assert len(tool_hints) == 1
    assert tool_hints[0]["name"] == "retrieve_knowledge"
    assert events[-1] == {"type": "end"}
