from __future__ import annotations
import json
import logging
import os
import time
from typing import Any

import boto3

from ck_agent.agent import run_agent_stream
from ck_agent.session_store import (
    get_or_create_session,
    save_message,
    delete_session,
)

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def _apigw_client(event: dict):
    domain = event["requestContext"]["domainName"]
    stage = event["requestContext"]["stage"]
    return boto3.client("apigatewaymanagementapi", endpoint_url=f"https://{domain}/{stage}")


def _send(apigw, connection_id: str, payload: dict) -> None:
    try:
        apigw.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
    except apigw.exceptions.GoneException:
        logger.warning("Connection %s is gone", connection_id)


def handler(event: dict, context: Any) -> dict:
    route_key = event.get("requestContext", {}).get("routeKey", "")
    connection_id = event.get("requestContext", {}).get("connectionId", "")

    logger.info(json.dumps({"event": "route", "route_key": route_key, "connection_id": connection_id}))

    if route_key == "$connect":
        return {"statusCode": 200}

    if route_key == "$disconnect":
        delete_session(connection_id)
        return {"statusCode": 200}

    if route_key == "$default":
        return _handle_message(event, connection_id)

    return {"statusCode": 400, "body": f"Unknown route: {route_key}"}


def _handle_message(event: dict, connection_id: str) -> dict:
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

    def _save(msg: dict) -> None:
        save_message(conversation_id, len(messages), msg)

    for event in run_agent_stream(messages, save_message_fn=_save):
        _send(apigw, connection_id, event)

    latency_ms = int((time.time() - start) * 1000)
    logger.info(json.dumps({
        "event": "turn_complete",
        "conversation_id": conversation_id,
        "connection_id": connection_id,
        "latency_ms": latency_ms,
        "turn_number": len(messages),
    }))
    return {"statusCode": 200}
