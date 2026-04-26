# Observability Design

## Two categories of observability — different tools, different questions

### System observability — "Is the service healthy?"

Infrastructure-level signals. These answer operational questions: is the service up, is it slow, is it throwing errors? Captured automatically by AWS — no custom code needed.

**What we capture:**
| Signal | Source | Alert trigger |
|--------|--------|---------------|
| Lambda invocation count | CloudWatch Metrics (AWS/Lambda) | Sudden drop → upstream problem |
| Lambda error rate | CloudWatch Metrics (AWS/Lambda) | > 1% → page on-call |
| Lambda duration p50/p95/p99 | CloudWatch Metrics (AWS/Lambda) | p99 > 20s → Bedrock throttling |
| Lambda cold starts | CloudWatch Metrics (InitDuration) | Spikes → concurrency scaling |
| DynamoDB throttled requests | CloudWatch Metrics (AWS/DynamoDB) | > 0 → switch to provisioned |
| API Gateway 4xx / 5xx rates | CloudWatch Metrics (AWS/ApiGateway) | 5xx spike → Lambda errors |
| Bedrock invocation latency | CloudWatch Metrics (AWS/Bedrock) | Drift → model performance issue |

**Key principle:** these metrics answer "is something broken?" — they do NOT tell you whether the agent is making good decisions.

---

### Agent-quality observability — "Is the agent doing the right thing?"

Application-semantic signals. These require custom structured logging because AWS has no concept of "verification success rate" or "retrieval relevance". Emitted by the Lambda as JSON events.

**Named events emitted:**

| Event | When emitted | Key fields |
|-------|-------------|------------|
| `route` | Every WebSocket invocation | `route_key`, `connection_id` |
| `turn_complete` | End of every agent turn | `conversation_id`, `latency_ms`, `turn_number` |
| `tool_invoked` | After each tool dispatch | `tool_name`, `duration_ms`, `conversation_id` |
| `verification_attempt` | After each `check_order_status` call | `outcome` (success/failure), `failure_reason`, `conversation_id` |

**What these answer:**
- **Are users completing the verification flow?** → verification_attempt success rate
- **Which capability do users want most?** → tool_invoked distribution (retrieve_knowledge vs check_order_status)
- **Is retrieval slow relative to LLM?** → tool_invoked duration_ms for retrieve_knowledge
- **Where in the conversation do users drop off?** → turn_number distribution at turn_complete

**Key principle:** a perfectly healthy service (zero Lambda errors, p99 latency = 2s) can still give wrong answers. These metrics answer questions that CloudWatch metrics cannot.

---

## What we built for this assessment

- 4 named structured log events in JSON format
- CloudWatch dashboard `ck-agent-ops` with 5 widgets (Lambda metrics + Log Insights)
- 5 saved Log Insights queries in `docs/observability_queries.md`

## What we'd add with more time

### Short-term (1–2 sprints)

**AWS X-Ray distributed tracing**
End-to-end traces spanning API Gateway → Lambda → Bedrock → DynamoDB. Each conversation turn becomes a trace; each tool call becomes a subsegment. Enables "find the slowest 1% of conversations and explain why."

**CloudWatch Alarms + SNS**
Automated paging on: p99 latency > 20s, error rate > 1%, verification failure spike (> 30% failure rate in 5 min could indicate a broken flow or brute-force attempt).

**PII scrubbing in log preprocessing**
Current logs may contain user inputs including raw date of birth. A Kinesis Firehose + Lambda transform step would redact PII before logs reach CloudWatch — required for production under GDPR/CCPA.

### Medium-term

**LangFuse or LangSmith integration**
Agent-specific observability platforms that capture: full prompt/response pairs, token counts per turn, tool-use decision paths, cost-per-conversation. Structured around conversations, not Lambda invocations — a much better unit for debugging agent behavior.

**Nightly eval harness**
A scheduled Lambda that replays 20 "golden" conversations (known correct answers), checks that retrieval still returns the right document for each query, and flags regressions. This is the difference between "we hope it still works" and "we know it still works."

**User feedback capture**
A thumbs up/down in the frontend that stores `{conversation_id, turn_number, rating}` to DynamoDB. Correlate with `tool_invoked` and `verification_attempt` events to identify which flows users find unhelpful.

---

## Key design principle

> Every event emitted should answer a specific question that someone will ask at 2am or in a quarterly review. If an event doesn't map to a concrete question, it's noise.

We kept the event taxonomy small — 4 named events — each mapping to a distinct operational or quality question. Adding more events is cheap; adding meaningful *interpretation* of those events is expensive. Start small, add when you have a specific question you can't answer.
