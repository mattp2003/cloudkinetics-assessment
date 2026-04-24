# Phase 12 — Observability

## Prerequisites

- [ ] Phase 11 complete
- [ ] Structured logging already emitting from Lambda (phase 08)

## Goal

A CloudWatch dashboard showing 4-5 meaningful widgets, plus at least 2 Log Insights queries saved. The distinction between *system metrics* and *agent-quality metrics* is the differentiator you want to show off in the design doc.

## Context for Claude Code

- Most of this is configured in the AWS Console — faster than CDK for dashboards
- Do take a screenshot of the final dashboard for the slide deck
- Do save Log Insights queries to the repo so the reviewer can reproduce them

## Steps

### 12.1 — Ensure Lambda emits enough structured events

Verify that your Lambda handler emits:
- `{"event": "turn_complete", "conversation_id": ..., "latency_ms": ..., "tool_calls": ...}`
- `{"event": "tool_invoked", "tool_name": "...", "duration_ms": ..., "conversation_id": ...}` (add if missing)
- `{"event": "verification_attempt", "outcome": "success"|"failure", "failure_reason": "..."}` (add if missing)
- `{"event": "route", "route_key": ..., "connection_id": ...}` (already exists)

Add any missing ones now. Example addition around the tool dispatch:
```python
tool_start = time.time()
result = dispatch_tool(tu["name"], tu["input"])
logger.info(json.dumps({
    "event": "tool_invoked",
    "tool_name": tu["name"],
    "duration_ms": int((time.time() - tool_start) * 1000),
    "conversation_id": conversation_id,
}))
```

For verification outcome, hook into `check_order_status` via the handler — not the tool itself — so you log the outcome without changing tool response shape. Detect by inspecting the returned dict.

Redeploy: `cdk deploy -c kb_id=$BEDROCK_KB_ID --hotswap`.

Run a handful of test conversations via the frontend or wscat to generate log data.

### 12.2 — Create Log Insights queries

Save these in `docs/observability_queries.md` so the reviewer can run them:

**Query 1 — Turn latency distribution (p50/p95/p99):**
```
fields @timestamp, @message
| filter @message like /turn_complete/
| parse @message "*\"latency_ms\": *," as _, latency_ms
| stats avg(latency_ms), pct(latency_ms, 50), pct(latency_ms, 95), pct(latency_ms, 99) by bin(5m)
```

**Query 2 — Tool call distribution:**
```
fields @timestamp, @message
| filter @message like /tool_invoked/
| parse @message "*\"tool_name\": \"*\"*" as _, tool_name, _2
| stats count() as invocations by tool_name
```

**Query 3 — Verification success rate:**
```
fields @timestamp, @message
| filter @message like /verification_attempt/
| parse @message "*\"outcome\": \"*\"*" as _, outcome, _2
| stats count() as attempts by outcome
```

**Query 4 — Error rate:**
```
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Traceback/
| stats count() by bin(1h)
```

### 12.3 — Build CloudWatch dashboard in console

Go to CloudWatch → Dashboards → Create dashboard. Name: `ck-agent-ops`.

**Widget 1 — Invocation count + error rate (line chart):**
- Metric: `AWS/Lambda` → `Invocations` + `Errors` for `ck-agent-handler`
- Period: 1 min

**Widget 2 — p50 / p95 / p99 latency (line chart):**
- Metric: `AWS/Lambda` → `Duration` (p50, p95, p99)

**Widget 3 — Turn latency from custom logs (Log Insights widget):**
- Use Query 1 above
- Visualization: line

**Widget 4 — Tool call distribution (pie or bar):**
- Use Query 2

**Widget 5 — Verification outcomes (bar):**
- Use Query 3

**Save the dashboard.** Take a high-res screenshot — it goes directly into the slide deck.

### 12.4 — Write `docs/observability.md`

Structure the document around this distinction (it's the thing that makes the design doc stand out):

```markdown
# Observability Design

## Two categories of observability, different tools

### System observability — "is the service healthy?"
Latency, error rates, throughput, cold starts, throttling. These are infrastructure concerns and are captured by CloudWatch metrics natively. Every request emits these.

**What we capture:**
- Lambda duration (p50/p95/p99), error count, invocation count, throttles
- API Gateway connection count, 4xx/5xx rates
- DynamoDB read/write capacity consumed, throttled requests
- Bedrock model invocation latency (exposed via CloudWatch automatically)

**Why this matters:** you need these to page an on-call engineer when things break. They answer questions like "is my service down?" not "is my agent making good decisions?"

### Agent-quality observability — "is the agent doing the right thing?"
Tool call correctness, retrieval hit relevance, verification abandonment rates, conversation completion. These are application-semantic and require custom logging.

**What we capture:**
- Per-turn: conversation_id, tool_calls made, retrieval hit count, latency
- Per tool call: tool name, input args (sanitized), duration
- Per verification attempt: outcome (success/failure), anonymized failure reason
- (Future) User feedback signals: thumbs up/down on responses

**Why this matters:** a perfectly healthy service can still give wrong answers. These metrics answer "is retrieval getting better over time?", "where in the verification flow do users drop off?", "which tools are being over- or under-used?"

## What we built for this assessment
- Structured JSON logging with 4 named events
- 4 Log Insights queries saved in docs/observability_queries.md
- CloudWatch dashboard `ck-agent-ops` with 5 widgets

## What we'd add next (with more time)
- **AWS X-Ray distributed tracing** so each conversation turn shows as a trace spanning API Gateway → Lambda → Bedrock → DDB
- **LangFuse or LangSmith integration** for agent-specific traces (tool-use decision paths, prompt-response pairs, cost-per-turn)
- **Eval harness running on a schedule**: replay a fixed set of 20 golden conversations nightly, flag regressions in retrieval hit rate or tool call correctness
- **User feedback capture**: a thumbs up/down in the UI that stores feedback linked to conversation_id
- **PII scrubbing**: current logs may contain user inputs including raw DOB; a preprocessing step would redact before persistence
- **Alerting**: CloudWatch alarms on p99 latency, error rate, verification failure spike (could indicate attack or broken flow)

## Key design principle
Every event emitted by the system should answer a specific question that someone will ask at some point. If an event doesn't map to a question, it's noise. We kept the event taxonomy small: 4 named events, each with a clear purpose.
```

## Verification (human-runnable)

```bash
# Dashboard exists
aws cloudwatch list-dashboards --region us-east-1 --query "DashboardEntries[?DashboardName=='ck-agent-ops']"
# Expected: non-empty

# Log Insights queries return data (run at least one)
aws logs start-query \
  --log-group-name /aws/lambda/ck-agent-handler \
  --start-time $(($(date +%s) - 3600)) \
  --end-time $(date +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /turn_complete/ | limit 20' \
  --region us-east-1
# Expected: queryId returned

# docs/observability.md and docs/observability_queries.md exist and are non-trivial
wc -l docs/observability.md docs/observability_queries.md
# Expected: both > 30 lines
```

## Definition of Done

- [ ] Lambda emits 4 event types reliably
- [ ] `ck-agent-ops` dashboard exists in CloudWatch with 5 widgets
- [ ] Screenshot of dashboard saved to `docs/screenshots/dashboard.png`
- [ ] 4 Log Insights queries saved to `docs/observability_queries.md`
- [ ] `docs/observability.md` explains the system-vs-agent distinction
- [ ] **Level 300 implementation complete** (data model + observability)

## Out of Scope

- ❌ X-Ray / tracing (designed only)
- ❌ LangFuse integration (designed only)
- ❌ Alerting rules (designed only)
- ❌ Eval harness (designed only)
- ❌ Infra-as-code for the dashboard (console-created is fine; IaC-able with `CfnDashboard` if time)

## Commit Message

```
[phase 12] Observability — structured logs, dashboard, queries

- 4 log event types: route, turn_complete, tool_invoked, verification_attempt
- CloudWatch dashboard ck-agent-ops: Lambda metrics + custom Log Insights widgets
- 4 saved queries in docs/observability_queries.md
- docs/observability.md articulates system-vs-agent observability philosophy
- Level 300 implementation complete
- Reference: plans/12_observability.md
```
