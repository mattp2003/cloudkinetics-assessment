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

SESSION_TTL_SECONDS = 2 * 60 * 60          # 2 hours
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
    """Returns {conversation_id, messages, verification_state}. Creates new session if none exists."""
    resp = SESSIONS_TABLE.get_item(Key={"connection_id": connection_id})
    if "Item" in resp:
        item = resp["Item"]
        conversation_id = item["conversation_id"]
        messages = load_messages(conversation_id)
        return {
            "conversation_id": conversation_id,
            "messages": messages,
            "verification_state": item.get("verification_state", {}),
        }

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
        ScanIndexForward=True,
    )
    return [json.loads(item["payload"]) for item in resp.get("Items", [])]


def save_message(conversation_id: str, turn_number: int, message: dict, user_id: str | None = None) -> None:
    """Persist one message to the conversation log."""
    ts = time.time()
    sk = f"MSG#{int(ts * 1000):013d}#{uuid.uuid4().hex[:8]}"
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
