# Phase 08 — Lambda Handler

## Prerequisites

- [ ] Phase 07 complete (CDK synthesizes)
- [ ] Local agent from phase 04 still works

## Goal

A Lambda handler that accepts API Gateway WebSocket events, routes by `routeKey` (`$connect` / `$disconnect` / `$default`), and runs the agent loop for `$default` messages. Responses are posted back via `ApiGatewayManagementApi`.

**Streaming is deferred to phase 09** — this phase sends the full response at once, which is simpler to debug.

## Context for Claude Code

- WebSocket event shape: `event["requestContext"]["routeKey"]`, `event["requestContext"]["connectionId"]`, `event["body"]` for messages
- Agent code from phase 04 (`AgentSession`) is reused, but session state must come from DynamoDB (not in-memory) because Lambda is stateless
- Use `boto3` in Lambda. No new dependencies needed beyond what CDK bundled.

## Steps

### 8.1 — Refactor session persistence into a new module

Create `src/ck_agent/session_store.py`:

```python
from __future__ import annotations
import json
import os
import time
import uuid
from decimal import Decimal
from typing import Any

import boto3

DDB = boto3.resource("dynamodb")
CONVERSATIONS_TABLE = DDB.Table(os.environ.get("CONVERSATIONS_TABLE", "ck-conversations"))
SESSIONS_TABLE = DDB.Table(os.environ.get("SESSIONS_TABLE", "ck-sessions"))

SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours
CONVERSATION_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days

def _clean(obj: Any) -> Any:
    """Recursively convert Python types to DDB-compatible types."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(i) for i in obj]
    return obj


def get_or_create_session(connection_id: str) -> dict:
    """Returns {conversation_id, messages: [...]}. Creates new session if none exists."""
    resp = SESSIONS_TABLE.get_item(Key={"connection_id": connection_id})
    if "Item" in resp:
        item = resp["Item"]
        conversation_id = item["conversation_id"]
        messages = load_messages(conversation_id)
        return {"conversation_id": conversation_id, "messages": messages, "verification_state": item.get("verification_state", {})}

    conversation_id = str(uuid.uuid4())
    SESSIONS_TABLE.put_item(Item={
        "connection_id": connection_id,
        "conversation_id": conversation_id,
        "verification_state": {},
        "created_at": int(time.time()),
        "ttl": int(time.time()) + SESSION_TTL_SECONDS,
    })
    return {"conversation_id": conversation_id, "messages": [], "verification_state": {}}


def load_messages(conversation_id: str) -> list[dict]:
    """Load all messages for a conversation, ordered chronologically."""
    resp = CONVERSATIONS_TABLE.query(
        KeyConditionExpression="conversation_id = :cid",
        ExpressionAttributeValues={":cid": conversation_id},
        ScanIndexForward=True,  # chronological
    )
    return [json.loads(item["payload"]) for item in resp.get("Items", [])]


def save_message(conversation_id: str, turn_number: int, message: dict, user_id: str | None = None) -> None:
    """Persist one message to the conversation log."""
    ts = time.time()
    sk = f"MSG#{int(ts*1000):013d}#{uuid.uuid4().hex[:8]}"
    CONVERSATIONS_TABLE.put_item(Item=_clean({
        "conversation_id": conversation_id,
        "sk": sk,
        "turn_number": turn_number,
        "payload": json.dumps(message),
        "role": message.get("role"),
        "user_id": user_id or "anonymous",
        "ttl": int(ts) + CONVERSATION_TTL_SECONDS,
    }))


def delete_session(connection_id: str) -> None:
    SESSIONS_TABLE.delete_item(Key={"connection_id": connection_id})
```

### 8.2 — Lambda handler: `src/ck_agent/lambda_handler.py`

```python
from __future__ import annotations
import json
import logging
import os
import time
from typing import Any

import boto3

from ck_agent.agent import BEDROCK, MODEL_ID, SYSTEM_PROMPT, MAX_TOOL_ITERATIONS
from ck_agent.tools import TOOL_CONFIG, dispatch_tool
from ck_agent.session_store import (
    get_or_create_session,
    save_message,
    delete_session,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

WEBSOCKET_ENDPOINT = os.environ.get("WEBSOCKET_ENDPOINT", "")


def _apigw_client(event):
    """Client for posting messages back to the WebSocket connection."""
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]
    endpoint = f"https://{domain}/{stage}"
    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)


def _send(apigw, connection_id: str, payload: dict) -> None:
    try:
        apigw.post_to_connection(ConnectionId=connection_id, Data=json.dumps(payload).encode("utf-8"))
    except apigw.exceptions.GoneException:
        logger.warning("Connection %s is gone", connection_id)


def handler(event: dict, context: Any) -> dict:
    route_key = event.get("requestContext", {}).get("routeKey", "")
    connection_id = event.get("requestContext", {}).get("connectionId", "")

    logger.info(json.dumps({"event": "route", "route_key": route_key, "connection_id": connection_id}))

    if route_key == "$connect":
        # Session created lazily on first message
        return {"statusCode": 200}

    if route_key == "$disconnect":
        delete_session(connection_id)
        return {"statusCode": 200}

    if route_key == "$default":
        return handle_message(event, connection_id)

    return {"statusCode": 400, "body": f"Unknown route: {route_key}"}


def handle_message(event: dict, connection_id: str) -> dict:
    """Process an incoming user message and respond."""
    try:
        body = json.loads(event.get("body", "{}"))
        user_text = body.get("message", "").strip()
    except json.JSONDecodeError:
        user_text = event.get("body", "").strip()

    if not user_text:
        return {"statusCode": 400, "body": "empty message"}

    apigw = _apigw_client(event)
    start = time.time()

    session = get_or_create_session(connection_id)
    conversation_id = session["conversation_id"]
    messages: list[dict] = session["messages"]

    user_msg = {"role": "user", "content": [{"text": user_text}]}
    messages.append(user_msg)
    save_message(conversation_id, len(messages), user_msg)

    tool_call_count = 0
    final_text = "[no response]"

    for _ in range(MAX_TOOL_ITERATIONS):
        response = BEDROCK.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"temperature": 0.3, "maxTokens": 1024},
        )
        output_message = response["output"]["message"]
        messages.append(output_message)
        save_message(conversation_id, len(messages), output_message)

        stop_reason = response["stopReason"]
        if stop_reason == "end_turn":
            for block in output_message["content"]:
                if "text" in block:
                    final_text = block["text"]
            break

        if stop_reason == "tool_use":
            tool_call_count += 1
            tool_results = []
            for block in output_message["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = dispatch_tool(tu["name"], tu["input"])
                    result_str = result if isinstance(result, str) else json.dumps(result)
                    tool_results.append({
                        "toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": result_str}]}
                    })
            tool_result_msg = {"role": "user", "content": tool_results}
            messages.append(tool_result_msg)
            save_message(conversation_id, len(messages), tool_result_msg)
            continue

        break

    latency_ms = int((time.time() - start) * 1000)
    logger.info(json.dumps({
        "event": "turn_complete",
        "conversation_id": conversation_id,
        "connection_id": connection_id,
        "latency_ms": latency_ms,
        "tool_calls": tool_call_count,
        "turn_number": len(messages),
    }))

    _send(apigw, connection_id, {"type": "response", "text": final_text, "conversation_id": conversation_id})
    return {"statusCode": 200}
```

### 8.3 — Update bundling in CDK

The Lambda bundling command in phase 07 copies `ck_agent` — make sure it installs `boto3` and `pydantic`. Update `cdk/ck_agent_stack.py` bundling command if needed:

```python
command=[
    "bash", "-c",
    "pip install --no-cache-dir pydantic python-dateutil -t /asset-output && "
    "cp -r ck_agent /asset-output/"
],
```

(`boto3` is provided by Lambda runtime; don't bundle it — saves 10 MB.)

## Verification (human-runnable)

```bash
# Lambda code imports cleanly (local sanity check)
python -c "from ck_agent.lambda_handler import handler; print('OK')"
# Expected: OK

# CDK synth still passes with real handler
cd cdk && cdk synth -c kb_id=$BEDROCK_KB_ID > /dev/null
# Expected: exit 0, no errors

# Unit test the session store against local DDB (optional — easier to defer to live deploy test)
```

## Definition of Done

- [ ] `session_store.py` has `get_or_create_session`, `load_messages`, `save_message`, `delete_session`
- [ ] `lambda_handler.py` routes $connect, $disconnect, $default correctly
- [ ] Handler runs agent loop with persistence into DynamoDB
- [ ] Handler posts response back via `apigatewaymanagementapi`
- [ ] Structured logging emits `turn_complete` event with latency/tool_calls/turn_number
- [ ] `cdk synth` passes

## Out of Scope

- ❌ Streaming tokens — phase 09
- ❌ Deployment — phase 09
- ❌ CloudWatch dashboard — phase 12
- ❌ Error handling for Bedrock throttling (simple retry could be added in phase 12)

## Commit Message

```
[phase 08] Lambda handler with DynamoDB-backed sessions

- lambda_handler.py routes $connect/$disconnect/$default WebSocket events
- session_store.py persists conversation messages to DynamoDB
- get_or_create_session for new connections; delete_session on disconnect
- save_message on every turn (user + assistant + tool results)
- Non-streaming response (streaming comes in phase 09)
- Structured logging with turn_complete event
- Reference: plans/08_lambda_handler.md
```
