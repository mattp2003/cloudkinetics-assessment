# CloudWatch Log Insights Queries

Log group: `/aws/lambda/ck-agent-handler`

---

## Query 1 — Turn latency distribution (p50 / p95 / p99)

Answers: "How fast is the agent end-to-end? Is latency trending up?"

```
fields @timestamp, @message
| filter @message like /turn_complete/
| parse @message '"latency_ms": *,' as latency_ms
| stats avg(latency_ms) as avg_ms,
        pct(latency_ms, 50) as p50_ms,
        pct(latency_ms, 95) as p95_ms,
        pct(latency_ms, 99) as p99_ms
  by bin(5m)
```

---

## Query 2 — Tool call distribution

Answers: "Which tools are being called? Are users asking policy questions or order questions?"

```
fields @timestamp, @message
| filter @message like /tool_invoked/
| parse @message '"tool_name": "*"' as tool_name
| stats count() as invocations, avg(duration_ms) as avg_duration_ms by tool_name
```

---

## Query 3 — Verification success rate

Answers: "How often does identity verification succeed? Is the flow confusing users?"

```
fields @timestamp, @message
| filter @message like /verification_attempt/
| parse @message '"outcome": "*"' as outcome
| stats count() as attempts by outcome
```

---

## Query 4 — Error rate over time

Answers: "Are there runtime errors? Did a deploy introduce regressions?"

```
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Traceback/
| stats count() as errors by bin(1h)
```

---

## Query 5 — Recent conversations (quick debug view)

Answers: "What did the last N conversations look like?"

```
fields @timestamp, @message
| filter @message like /turn_complete/
| parse @message '"conversation_id": "*"' as conversation_id
| parse @message '"latency_ms": *,' as latency_ms
| parse @message '"turn_number": *,' as turn_number
| sort @timestamp desc
| limit 20
```
