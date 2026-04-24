# Phase 09 — WebSocket Streaming & Deploy

## Prerequisites

- [ ] Phase 08 complete (Lambda handler processes messages, writes to DynamoDB, responds non-streamed)
- [ ] `cdk synth` passes

## Goal

Deploy the stack. Switch the Lambda from `converse` (full response) to `converse_stream` (token-by-token), posting each chunk to the client via the WebSocket. Test end-to-end with `wscat`.

**This phase completes Level 200 core requirements.**

## Context for Claude Code

- Streaming shape: `converse_stream` returns an event iterator. Each event has a type like `contentBlockDelta` (text chunk), `contentBlockStart` (tool use starts), `messageStop` (stop_reason), `metadata` (token counts)
- For each text delta, send a small JSON message to the WebSocket client with the chunk
- Tool-use calls still happen the same way — but the tool call itself is NOT streamed to the client (we only stream final text)
- Client needs to know when the response is complete → send a `{"type": "end"}` marker

## Steps

### 9.1 — Update agent module to support streaming

Extract the core tool loop into a generator function in `src/ck_agent/agent.py`:

```python
def run_agent_stream(messages: list[dict], save_message_fn=None) -> Generator[dict, None, list[dict]]:
    """
    Generator yielding events for the caller to send to the client.
    Event types yielded:
        {"type": "text_delta", "text": "..."}     — for streaming tokens
        {"type": "tool_use_start", "name": "..."} — optional, for UI hints
        {"type": "end"}                           — final
    Returns the updated messages list (caller can persist).
    """
    for iteration in range(MAX_TOOL_ITERATIONS):
        response = BEDROCK.converse_stream(
            modelId=MODEL_ID,
            messages=messages,
            system=[{"text": SYSTEM_PROMPT}],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"temperature": 0.3, "maxTokens": 1024},
        )

        # Accumulate the assistant message as we stream
        current_message = {"role": "assistant", "content": []}
        current_text = ""
        current_tool = None
        current_tool_input_json = ""
        stop_reason = None

        for event in response["stream"]:
            if "contentBlockStart" in event:
                block_start = event["contentBlockStart"]["start"]
                if "toolUse" in block_start:
                    current_tool = {
                        "toolUseId": block_start["toolUse"]["toolUseId"],
                        "name": block_start["toolUse"]["name"],
                        "input": "",
                    }
                    yield {"type": "tool_use_start", "name": current_tool["name"]}

            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    current_text += delta["text"]
                    yield {"type": "text_delta", "text": delta["text"]}
                elif "toolUse" in delta:
                    # Tool input JSON streams in fragments
                    current_tool_input_json += delta["toolUse"].get("input", "")

            elif "contentBlockStop" in event:
                if current_text:
                    current_message["content"].append({"text": current_text})
                    current_text = ""
                if current_tool:
                    import json as _json
                    try:
                        current_tool["input"] = _json.loads(current_tool_input_json) if current_tool_input_json else {}
                    except _json.JSONDecodeError:
                        current_tool["input"] = {}
                    current_message["content"].append({"toolUse": current_tool})
                    current_tool = None
                    current_tool_input_json = ""

            elif "messageStop" in event:
                stop_reason = event["messageStop"]["stopReason"]

        messages.append(current_message)
        if save_message_fn:
            save_message_fn(current_message)

        if stop_reason == "end_turn":
            yield {"type": "end"}
            return messages

        if stop_reason == "tool_use":
            tool_results = []
            for block in current_message["content"]:
                if "toolUse" in block:
                    tu = block["toolUse"]
                    import json as _json
                    result = dispatch_tool(tu["name"], tu["input"])
                    result_str = result if isinstance(result, str) else _json.dumps(result)
                    tool_results.append({
                        "toolResult": {"toolUseId": tu["toolUseId"], "content": [{"text": result_str}]}
                    })
            tool_result_msg = {"role": "user", "content": tool_results}
            messages.append(tool_result_msg)
            if save_message_fn:
                save_message_fn(tool_result_msg)
            continue

        yield {"type": "end"}
        return messages

    yield {"type": "end"}
    return messages
```

Keep the non-streaming `handle_user_message` method for local CLI use.

### 9.2 — Update Lambda handler to use the streaming generator

In `src/ck_agent/lambda_handler.py`, replace the body of `handle_message` tool loop with:

```python
from ck_agent.agent import run_agent_stream

# ... inside handle_message, after loading session ...

def _save(msg):
    save_message(conversation_id, len(messages), msg)

for event in run_agent_stream(messages, save_message_fn=_save):
    _send(apigw, connection_id, event)

latency_ms = int((time.time() - start) * 1000)
logger.info(json.dumps({
    "event": "turn_complete",
    "conversation_id": conversation_id,
    "latency_ms": latency_ms,
    "turn_number": len(messages),
}))
return {"statusCode": 200}
```

### 9.3 — Deploy!

```bash
cd cdk
cdk deploy -c kb_id=$BEDROCK_KB_ID --require-approval never
```

Deployment takes ~3-5 min. Watch for:
- `CkAgentStack: creating CloudFormation changeset...`
- Resource creation progress
- Final `Outputs:` section with WebSocketUrl

Save the WebSocket URL for testing.

### 9.4 — Test with wscat

Install wscat if not already: `npm install -g wscat`.

```bash
wscat -c wss://<api-id>.execute-api.us-east-1.amazonaws.com/prod
```

Then paste messages one at a time:
```json
{"message": "what is your return policy?"}
```

Expected behavior:
1. Several `{"type": "text_delta", "text": "..."}` messages stream in
2. Optionally a `{"type": "tool_use_start", ...}` event
3. Finally `{"type": "end"}`

Test the verification flow too:
```json
{"message": "I want to check my order status"}
{"message": "alice@ck1.com"}
{"message": "last 4 of my SSN is 0001"}
{"message": "March 15 1990"}
{"message": "ORD-2025-001"}
```

### 9.5 — Quick debug commands if anything breaks

```bash
# Tail Lambda logs
aws logs tail /aws/lambda/ck-agent-handler --follow --region us-east-1

# Inspect DynamoDB
aws dynamodb scan --table-name ck-conversations --region us-east-1 --max-items 10
aws dynamodb scan --table-name ck-sessions --region us-east-1

# Redeploy after code change
cd cdk && cdk deploy -c kb_id=$BEDROCK_KB_ID --require-approval never
# or for Lambda code only:
cd cdk && cdk deploy -c kb_id=$BEDROCK_KB_ID --hotswap
```

### 9.6 — Common gotchas

| Symptom | Fix |
|---------|-----|
| `AccessDeniedException` calling Bedrock from Lambda | Check Lambda role has `bedrock:InvokeModelWithResponseStream` |
| `ResourceNotFoundException` on KB | `BEDROCK_KB_ID` env var missing or wrong; redeploy with correct ctx |
| `GoneException` posting to connection | Client disconnected mid-stream; log + continue |
| Lambda timeout | Increase memory to 2048 (more vCPU); check for Bedrock throttling |
| `converse_stream` event missing expected fields | AWS SDK version mismatch — pin boto3 or update CDK bundling |
| First message slow (~5-10s) | Lambda cold start; acceptable for demo |

## Verification (human-runnable)

```bash
# Stack is deployed
aws cloudformation describe-stacks --stack-name CkAgentStack \
  --query "Stacks[0].StackStatus" --region us-east-1 --output text
# Expected: CREATE_COMPLETE or UPDATE_COMPLETE

# WebSocket URL is reachable
WS_URL=$(aws cloudformation describe-stacks --stack-name CkAgentStack \
  --query "Stacks[0].Outputs[?OutputKey=='WebSocketUrl'].OutputValue" \
  --region us-east-1 --output text)
echo $WS_URL
# Expected: wss://...execute-api.us-east-1.amazonaws.com/prod

# Lambda logs are being written
aws logs describe-log-streams --log-group-name /aws/lambda/ck-agent-handler \
  --region us-east-1 --limit 1 --query "logStreams[0].logStreamName"
# Expected: a log stream name (not empty)

# DynamoDB has entries after a test conversation via wscat
aws dynamodb scan --table-name ck-conversations --region us-east-1 \
  --select COUNT --query "Count"
# Expected: > 0 after a test run
```

## Definition of Done

- [ ] Stack deploys with `cdk deploy`
- [ ] `wscat` connects successfully
- [ ] Text streams back token-by-token (not as one big block)
- [ ] Tool calls still work in the streaming flow (verification + order lookup succeeds)
- [ ] Conversation persists to DynamoDB
- [ ] Lambda logs show structured JSON with turn_complete events
- [ ] **Level 200 core requirements met**

## Out of Scope

- ❌ Frontend UI (phase 10)
- ❌ CI/CD pipeline (phase 13)
- ❌ Full observability dashboard (phase 12)
- ❌ Production hardening (VPC, WAF, secrets in KMS)

## Commit Message

```
[phase 09] Streaming responses and first deploy

- agent.run_agent_stream generator for converse_stream event handling
- Lambda handler forwards text_delta events to WebSocket client
- Tool calls execute during stream; results re-fed to next iteration
- Deployed to AWS: CkAgentStack in us-east-1
- Manually verified via wscat: streaming works, verification flow works,
  multi-order selection works, conversation persists to DynamoDB
- Level 200 core complete
- Reference: plans/09_websocket_streaming.md
```
