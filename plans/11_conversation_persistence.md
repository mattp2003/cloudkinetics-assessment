# Phase 11 — Conversation Persistence (Verify & Polish)

## Prerequisites

- [ ] Phase 10 complete, demo recorded
- [ ] System deployed and working end-to-end
- [ ] Basic persistence already wired up in phase 08

## Goal

Confirm conversation persistence works correctly under realistic use, and add a "get user history" feature that exercises the GSI (`by_user`). This is primarily about **proving** the Level 300 data model works, not rebuilding it.

## Context for Claude Code

- Persistence already writes to `ck-conversations` from phase 08
- GSI `by_user` exists from phase 07 CDK
- Missing: nothing actually reads from the GSI yet. This phase adds a simple retrieval path (mainly for the design doc talking point).

## Steps

### 11.1 — Add a `get_user_history` function in `session_store.py`

```python
def get_user_history(user_id: str, limit: int = 20) -> list[dict]:
    """
    Return the most recent messages for a specific verified user, across all conversations.
    Uses the by_user GSI for efficient lookup.
    """
    resp = CONVERSATIONS_TABLE.query(
        IndexName="by_user",
        KeyConditionExpression="user_id = :uid",
        ExpressionAttributeValues={":uid": user_id},
        ScanIndexForward=False,  # newest first
        Limit=limit,
    )
    return [json.loads(item["payload"]) for item in resp.get("Items", [])]
```

### 11.2 — Update `save_message` to actually populate `user_id`

Currently, `user_id` is hardcoded to `"anonymous"` unless explicitly passed. We need the Lambda handler to pass the verified user's email as `user_id` once verification succeeds.

In `lambda_handler.py`, track verification state:
```python
# After each turn, inspect if verification has just succeeded and extract the user_id
# The simplest heuristic: after a successful check_order_status tool call, scan the tool result for verified=True
# Store the user_id (email) in the session record so subsequent save_message calls tag correctly
```

Simpler alternative: walk through `messages` after the loop, find any `toolResult` whose content has `"verified": true`, extract the email from the preceding `toolUse` input, update the session record.

Don't over-engineer this — the design doc can describe the cleaner "event bus" approach. The test is that the GSI query returns *something* for a user who has had a verified conversation.

### 11.3 — Add a test script `scripts/inspect_history.py`

```python
"""Quick CLI to inspect conversation history for a given user."""
import sys
import json
from ck_agent.cli import _load_env; _load_env()
from ck_agent.session_store import get_user_history

if len(sys.argv) < 2:
    print("usage: python scripts/inspect_history.py <user_email>")
    sys.exit(1)

history = get_user_history(sys.argv[1], limit=50)
print(f"Found {len(history)} messages for {sys.argv[1]}")
for msg in history:
    role = msg.get("role", "?")
    content = msg.get("content", [])
    text = next((b.get("text", "") for b in content if "text" in b), "[non-text]")
    print(f"  [{role}] {text[:100]}")
```

### 11.4 — Smoke test the full persistence loop

```bash
# Run a full conversation through the deployed system via wscat (or the frontend)
# Include verification so Alice becomes tagged as user_id=alice@ck1.com

# Then query the GSI
export $(grep -v '^#' .env | xargs)
python scripts/inspect_history.py alice@ck1.com
# Expected: several messages printed, including her questions and the agent's answers
```

### 11.5 — Note design considerations for the Sunday write-up

Write these as notes in `docs/data_model_notes.md` — they feed directly into the design doc:

- **Why DynamoDB over Postgres/Aurora**: conversational workloads are append-heavy, latency-sensitive, access-pattern-driven. DDB's single-digit-ms reads win. No joins needed.
- **Key schema**: `PK=conversation_id` groups a conversation into a single DDB partition — all messages for one conversation land on the same node, making `Query` fast and cheap. `SK=MSG#<timestamp>#<id>` sorts chronologically for natural replay.
- **GSI by user**: enables "show me everything this user has asked" without scanning. Eventually consistent, which is fine for analytics. Not used for real-time conversation retrieval.
- **TTL**: 90 days on conversations aligns with a reasonable data retention policy. Actual privacy/GDPR compliance would require per-user deletion endpoints too.
- **Scaling**: pay-per-request means no capacity planning for the demo. At scale, provisioned mode with auto-scaling is cheaper.
- **What this does NOT support**: full-text search across conversations (would need OpenSearch), real-time subscriptions to new messages (would need DynamoDB Streams + EventBridge), cross-region replication (Global Tables).

## Verification (human-runnable)

```bash
# Full conversation persists
aws dynamodb scan --table-name ck-conversations --region us-east-1 --select COUNT --query Count
# Expected: > 0 after a test conversation

# GSI is populated for verified users
aws dynamodb query --table-name ck-conversations --index-name by_user \
  --key-condition-expression "user_id = :uid" \
  --expression-attribute-values '{":uid": {"S": "alice@ck1.com"}}' \
  --region us-east-1 --select COUNT --query Count
# Expected: > 0 (requires having run a verified conversation as Alice)

# inspect_history script works
python scripts/inspect_history.py alice@ck1.com
# Expected: shows message history
```

## Definition of Done

- [ ] `get_user_history` function works against the GSI
- [ ] Lambda handler tags `user_id` correctly after verification succeeds
- [ ] `inspect_history.py` returns real data for a test user
- [ ] `docs/data_model_notes.md` has talking points for the design doc

## Out of Scope

- ❌ Conversation search / full-text search
- ❌ User-facing "view my history" UI
- ❌ Analytics aggregations (counts, trends)
- ❌ Cross-session memory / long-term user profiles

## Commit Message

```
[phase 11] Conversation persistence — GSI usage and tagging

- get_user_history() uses by_user GSI for efficient per-user lookup
- Lambda tags user_id on messages after successful verification
- scripts/inspect_history.py for manual inspection / demo
- docs/data_model_notes.md with design-doc talking points
- Reference: plans/11_conversation_persistence.md
```
