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
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"text": result_str}],
                        }
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

    _send(apigw, connection_id, {
        "type": "response",
        "text": final_text,
        "conversation_id": conversation_id,
    })
    return {"statusCode": 200}
