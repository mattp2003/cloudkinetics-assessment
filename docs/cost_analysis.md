# Cost Analysis

All prices in USD, region `us-east-1`, based on AWS published pricing as of April 2026.

---

## 1. Demo / Assessment Build (~2 weeks live)

**Assumptions:** ~50 test conversations during build (~5 turns each), ~20 reviewer queries after submission, KB has 3 documents under 1MB, deployment runs for ~2 weeks then torn down.

| Component | Quantity | Unit Cost | Total |
|---|---|---|---|
| Bedrock Claude Haiku 4.5 input | ~150K tokens | $0.80 / 1M | ~$0.12 |
| Bedrock Claude Haiku 4.5 output | ~30K tokens | $4.00 / 1M | ~$0.12 |
| KB ingestion — FM parsing (one-time) | 18 pages | ~$0.003/page | $0.06 |
| Titan Text Embeddings v2 | ~50K tokens | $0.02 / 1M | <$0.01 |
| S3 Vectors storage + queries | tiny corpus, ~70 queries | ~$0.06/GB/mo + $0.20/M queries | <$0.10 |
| Lambda invocations | ~200 × ~10s × 256MB | First 1M requests free | $0 |
| API Gateway WebSocket | ~500 messages | First 1M messages free | $0 |
| DynamoDB | <600 r/w ops | Pay-per-request, within free tier | $0 |
| S3 (source docs) | ~5MB | $0.023/GB/mo | $0 |
| CloudWatch Logs | <100MB | First 5GB/mo free | $0 |
| Data transfer out | <50MB | First 100GB/mo free | $0 |
| **Total** | | | **~$0.40** |

> **Cost trap avoided:** choosing S3 Vectors over OpenSearch Serverless saves ~$345/month in idle costs. OpenSearch Serverless has a 2 OCU minimum floor (~$345/mo) billed from collection creation regardless of query volume. S3 Vectors has no minimum. See [Section 5](#5-cost-traps) for details.

---

## 2. Production Scale: Small Business (1,000 conversations / month)

**Assumptions per conversation:** 5 turns, ~4K input tokens per turn (system prompt + tool config + history + retrieved chunks), ~600 output tokens per turn.

| Component | Calculation | Monthly Cost |
|---|---|---|
| Bedrock input tokens | 1,000 × 5 × 4K = 20M tokens × $0.80/1M | $16 |
| Bedrock output tokens | 1,000 × 5 × 600 = 3M tokens × $4.00/1M | $12 |
| Titan Embeddings | 5,000 queries × 200 tokens | <$0.01 |
| S3 Vectors | small dataset, low query volume | ~$1 |
| Lambda + API Gateway + DynamoDB | well within free tier | ~$2 |
| CloudWatch Logs | ~1GB | $0.50 |
| **Monthly Total** | | **~$32** |

**Per-conversation cost: ~$0.032**

---

## 3. Production Scale: Growing E-commerce (100,000 conversations / month)

| Component | Calculation | Monthly Cost |
|---|---|---|
| Bedrock input tokens | 100K × 5 × 4K = 2B tokens × $0.80/1M | $1,600 |
| Bedrock output tokens | 100K × 5 × 600 = 300M × $4.00/1M | $1,200 |
| Titan Embeddings | 500K queries × 200 tokens | ~$2 |
| S3 Vectors | scales with corpus, not queries | ~$10–50 |
| Lambda | ~500K invocations × 10s × 256MB | ~$20 |
| API Gateway WebSocket | ~10M messages | ~$30 |
| DynamoDB | ~10M writes, ~5M reads | ~$25 |
| CloudWatch Logs | ~100GB | ~$50 |
| Data transfer out | WebSocket egress | ~$20 |
| **Monthly Total** | | **~$3,000** |

**Per-conversation cost: ~$0.030**

---

## 4. Production Scale: Large E-commerce (1,000,000 conversations / month)

At this scale, prompt caching becomes essential — the system prompt and tool definitions are sent on every turn and are identical across all users.

| Component | Calculation | Monthly Cost |
|---|---|---|
| Bedrock input (cached portions — system prompt + tools) | ~60% of input tokens cached at $0.08/1M | ~$5,760 |
| Bedrock input (uncached — user messages + history) | ~40% of input tokens at $0.80/1M | ~$6,400 |
| Bedrock output tokens | 3B tokens × $4.00/1M | $12,000 |
| All other AWS services combined | Lambda, DDB, API GW, S3, CW | ~$500 |
| **Monthly Total (with caching)** | | **~$24,660** |

**Per-conversation cost: ~$0.025** (down from ~$0.032 thanks to prompt caching)

---

## 5. Cost Traps

Common pitfalls that would catch most teams off guard:

### OpenSearch Serverless Idle Floor
~$345/month from collection creation, even at zero traffic. This is the default vector store option in the Bedrock KB "Quick Create" flow. **Avoided here by explicitly selecting S3 Vectors.**

> Additionally: deleting the Bedrock Knowledge Base does **not** delete its OpenSearch Serverless collection. Charges continue indefinitely until the collection is manually deleted from the OpenSearch Serverless console.

### CloudWatch Logs Verbosity
At scale, logging full prompt + response on every turn can add hundreds of dollars per month in ingestion costs. **Mitigation:** log structured event names and IDs only, sample full payloads at 1–5%, redact PII before emission.

### NAT Gateway Data Transfer
$0.045/GB processed. Easy to overlook when adding VPC private networking later.

### Cross-Region Data Transfer
$0.02/GB. Relevant if the architecture goes multi-region. Plan global routing topology to minimise cross-region hops.

### Bedrock Regional vs Global Endpoints
Regional endpoints cost ~10% more than global CRIS (`global.` prefix) endpoints. Default to global inference profiles unless data residency requirements demand otherwise.

---

## 6. Cost Optimisations (Applied Progressively at Scale)

| Optimisation | Impact | When to Apply |
|---|---|---|
| **Prompt caching** for system prompt + tool definitions | Up to 90% reduction on cached input tokens | From day one — zero engineering effort to enable |
| **Route simple flows to Haiku** | ~67% cheaper per turn vs Sonnet for verification-only flows | Once traffic > 10K conversations/month |
| **Batch API** for offline analytics | 50% token discount | When running eval pipelines or summarisation jobs |
| **DynamoDB provisioned capacity** | 30–50% cheaper than pay-per-request | Once traffic patterns are stable and predictable |
| **Bedrock Provisioned Throughput** | Significant discount at sustained volume | Only after traffic is stable at >100K conversations/day |

---

## 7. Unit Economics Summary

| Scale | Cost / Conversation | vs. Human Support ($5–$15/ticket) |
|---|---|---|
| Demo (70 conversations) | ~$0.006 | 800–2,500× cheaper |
| Small business (1K/mo) | ~$0.032 | 156–469× cheaper |
| Growing (100K/mo) | ~$0.030 | 167–500× cheaper |
| Large (1M/mo, optimised) | ~$0.025 | 200–600× cheaper |

The agent is **100–500× cheaper per inquiry** than human-handled support (industry benchmark: $5–$15 fully-loaded cost per resolved ticket). The business question is therefore not *"is it affordable?"* but *"is the quality high enough to deflect human-routed tickets?"* — which is precisely what the observability and evaluation systems in Level 300 are designed to measure.

---

## 8. Teardown Checklist

Run in this exact order after the assessment is reviewed to avoid leftover charges:

1. `cd cdk && cdk destroy` — removes Lambda, API Gateway, DynamoDB tables, IAM roles
2. Bedrock Console → Knowledge Bases → delete `ck-kb-policies-and-10k`
3. S3 Console → empty and delete `ck-knowledge-docs-<account_id>` bucket
4. S3 Vectors Console → delete the vector bucket created by the KB
5. OpenSearch Serverless Console → confirm no collections remain
6. CloudWatch Logs → delete `/aws/lambda/ck-agent-handler` log group (optional)

After teardown, set a billing alarm at $5/month and check Cost Explorer one week later to confirm nothing is silently accumulating.

---

*Prices sourced from AWS Bedrock, S3 Vectors, Lambda, DynamoDB, and API Gateway pricing pages. All figures verified April 2026, region `us-east-1`.*
