# Architectural Decisions — LOCKED

**This file is the north star. Claude Code reads this at the start of every session. Do not modify during implementation. Revisit only during design-doc writing on Sunday.**

---

## Problem statement (one sentence)

Build an agentic conversational system for a US e-commerce company that (1) answers questions from internal documents via RAG, and (2) verifies users by email/SSN-last-4/DOB before returning order status.

## Cloud & runtime

| Decision | Value | Rationale |
|----------|-------|-----------|
| Cloud provider | AWS | Preferred by assessment; matches Matthew's FCAJ stack |
| Region | `us-east-1` | Best Bedrock model availability |
| Python version | 3.13 | Latest stable; Lambda-supported |
| LLM | Claude Sonnet 4.6 via Bedrock Converse API | Latest (released Feb 2026); 1M-token context, strong tool-use, streaming, managed |
| LLM model ID | `global.anthropic.claude-sonnet-4-6-v1:0` (Global CRIS profile) | Global cross-region inference profile — higher throughput and availability. Drop the `global.` prefix for regional routing if needed. Fallback: `global.anthropic.claude-sonnet-4-5-v1:0`. |
| RAG | Bedrock Knowledge Base | Managed chunking + OpenSearch Serverless saves ~6h build time |
| Chunking strategy | Hierarchical chunking (parent 1500 / child 300 / overlap 60) | Preserves document structure; right choice for 10-K |
| Parser | Foundation Model parsing using Claude (Sonnet 4.6 if offered by KB console; otherwise whichever current Claude the KB dropdown offers) | Handles tables in 10-K (pages 16, 18). KB uses model ARNs for the parser, not inference profile IDs — select from the KB console dropdown. |
| Embeddings | Amazon Titan Text Embeddings v2 | KB default, 1024 dims |
| Vector store | OpenSearch Serverless (auto-provisioned by KB) | Managed |
| Agent orchestration | Python in AWS Lambda | Serverless fits request-response; no idle cost |
| API layer | API Gateway WebSocket API | Required for streaming responses |
| Data store | DynamoDB | Sub-10ms reads, schema flexibility, low ops overhead |
| IaC | AWS CDK in Python | Matthew's stack; type-checked; easier than raw CloudFormation |
| CI/CD | GitHub Actions | Free tier sufficient; CDK deploy on main branch |
| Frontend | Single HTML file with vanilla JS WebSocket client | Minimal scope; reviewer cares about backend |

## Data model

**DynamoDB tables:**

1. **`ck-conversations`**
   - PK: `conversation_id` (string, UUID)
   - SK: `sk` (string, format: `MSG#<ISO8601_timestamp>#<message_id>`)
   - Attributes: `role`, `content`, `tool_calls`, `tool_results`, `turn_number`, `user_id` (if verified)
   - GSI1: PK=`user_id`, SK=`conversation_id#timestamp` (for user history retrieval)
   - TTL attribute: `ttl` (90 days — privacy/compliance)

2. **`ck-sessions`**
   - PK: `connection_id` (WebSocket connection ID)
   - Attributes: `conversation_id`, `verification_state` (JSON), `created_at`
   - TTL: 2 hours (WebSocket idle limit is 10 min anyway)

3. **`ck-mock-users`** (seeded mock data — simulates the company's user DB)
   - PK: `email`
   - Attributes: `full_name`, `ssn_full`, `dob_iso`, `orders` (list of maps)

## Naming conventions

- Resource prefix: `ck-` (CloudKinetics)
- Stack name: `CkAgentStack`
- Lambda function: `ck-agent-handler`
- Log groups: `/aws/lambda/ck-agent-handler`
- S3 bucket for docs: `ck-knowledge-docs-<account_id>-<region>`
- Python module prefix: `ck_agent`

## Verification requirements (from assessment)

1. **Email pattern**: `^[a-zA-Z0-9._%+-]+@ck\d+\.com$` (e.g., `user@ck1.com`, `user@ck123.com`)
2. **SSN last-4**: Strip all non-digits from input, take last 4 characters
3. **DOB**: Accept any natural-language format; parse via structured LLM call to ISO `YYYY-MM-DD`
4. **Never disclose order info before all three are collected AND validated**
5. **When multiple orders exist**: present list, ask user to pick, never assume

## Known out-of-scope (intentionally not building)

- User signup / account creation
- Real payment processing
- Multi-language support (English only)
- Cross-session memory / user profiles
- Load testing
- Production security hardening (KMS CMKs, VPC, WAF, etc. — designed in doc only)
- Request classification pipeline (designed only, Level 300 Optional #4)
- Data preprocessing pipeline beyond KB config (designed only, Level 300 Optional #5)

## Fallback decisions (if primary path fails)

| Primary | Fallback | Trigger |
|---------|----------|---------|
| Bedrock KB | FAISS in-Lambda with sentence-transformers | KB quota issues or ingestion fails by Saturday 2pm |
| API Gateway WebSocket | API Gateway HTTP + non-streaming response | WebSocket deployment blocks progress past Saturday 5pm |
| Bedrock Claude Sonnet 4.6 | Claude Sonnet 4.5 (`global.anthropic.claude-sonnet-4-5-v1:0`) or Claude Haiku 4.5 (`global.anthropic.claude-haiku-4-5-v1:0`) | Model not available in account's region |
| CDK deploy | Console-based deployment, IaC written but not deployed | CDK bootstrap/deploy issues past Saturday 4pm |

---

*Last updated: Day 0 (Friday evening planning). Do not update without explicit decision.*
