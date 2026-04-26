# Data Model Design Notes

Talking points for the design doc and interview prep.

## Why DynamoDB over RDS/Aurora

Conversational workloads are **append-heavy, latency-sensitive, and access-pattern-driven**:
- Every message is a write; reads happen only on reconnect to replay history
- Single-digit-ms reads/writes are needed to keep the agent loop responsive
- The access patterns are fixed: "get all messages for this conversation" and "get recent messages for this user" — DynamoDB's key-based model is a perfect fit
- No joins are needed: a conversation is a self-contained unit

RDS would add connection pool management, schema migrations, and ~10–30ms query overhead with no benefit for this workload.

## Key Schema

```
Table: ck-conversations
  PK  = conversation_id  (UUID)
  SK  = MSG#<timestamp_ms>#<random_suffix>

GSI: by_user
  PK  = user_id          (email, e.g. alice@ck1.com)
  SK  = MSG#<timestamp_ms>#<random_suffix>
```

**Why this shape:**
- `PK = conversation_id` groups all messages for one conversation into a single DynamoDB partition → a single `Query` call retrieves the full history, touching only one shard
- `SK = MSG#<timestamp>` gives chronological sort for free; replaying the conversation just means reading the partition in order
- The `MSG#` prefix in the sort key future-proofs for adding other record types (e.g. `META#conversation`) to the same partition without collision

## GSI: `by_user`

Enables "show me everything this user has asked" across all conversations without a full table scan.

- **Eventually consistent** — fine for analytics; real-time conversation replay uses the main table
- **Populated** when a user's email is confirmed through the verification flow (`check_order_status` tool call)
- Messages before verification are tagged `user_id = "anonymous"` and excluded from per-user queries

## TTL Policy

| Record type    | TTL        | Rationale                                      |
|----------------|------------|------------------------------------------------|
| Conversations  | 90 days    | Reasonable support history window              |
| Sessions       | 2 hours    | WebSocket session lifetime; stale connections auto-expire |

Actual GDPR/privacy compliance would add per-user deletion endpoints (scan by_user GSI, delete items).

## Billing Mode

`PAY_PER_REQUEST` for the demo — no capacity planning needed, cost scales to zero when idle.

At production scale, switch to **provisioned mode with auto-scaling** (typically ~30–40% cheaper under sustained load). Rule of thumb: if avg RCU/WCU > 50% of provisioned for > 30 min/day, provisioned pays off.

## What This Model Does NOT Support

| Need | Required addition |
|------|------------------|
| Full-text search across conversations | OpenSearch Serverless + DynamoDB Streams |
| Real-time multi-device sync | DynamoDB Streams + WebSocket fan-out |
| Cross-region replication | DynamoDB Global Tables |
| Long-term analytics | DynamoDB Streams → S3 → Athena |
| Per-user hard delete (GDPR) | Scan by_user GSI, batch delete items |

## Session Table

```
Table: ck-sessions
  PK = connection_id   (API Gateway WebSocket connection ID)
  Attributes: conversation_id, user_id, verification_state, created_at, ttl
```

Maps each live WebSocket connection to a conversation. Deleted on `$disconnect` or expired by TTL after 2 hours. Conversation history in `ck-conversations` outlives the session.
