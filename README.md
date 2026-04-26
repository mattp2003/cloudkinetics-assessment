# CK Agent — Agentic Conversational System

A serverless, streaming AI customer service agent for a US-based e-commerce company. The agent answers questions from internal documents via RAG and performs identity-verified order status lookups over a real-time WebSocket connection.

**Live demo:** https://mattp2003.github.io/cloudkinetics-assessment/

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Core Components](#core-components)
  - [Agent Loop](#agent-loop)
  - [Tools](#tools)
  - [Identity Verification](#identity-verification)
  - [Session Persistence](#session-persistence)
  - [Observability](#observability)
- [Knowledge Base](#knowledge-base)
- [Infrastructure](#infrastructure)
- [CI/CD](#cicd)
- [Testing](#testing)
- [Local Development](#local-development)
- [Deployment](#deployment)
- [Environment Variables](#environment-variables)
- [Mock Users](#mock-users)
- [Design Decisions](#design-decisions)
- [Known Limitations](#known-limitations)

---

## Overview

The agent runs entirely on AWS serverless infrastructure with no persistent servers. Users connect via WebSocket and receive token-by-token streamed responses. The system has two capabilities:

1. **RAG (Retrieval-Augmented Generation)** — answers questions about company policies, shipping, returns, and general information by querying a Bedrock Knowledge Base backed by internal documents
2. **Identity-verified order lookup** — collects email, SSN last-4, and date of birth conversationally, verifies the user, then returns order details

---

## Architecture

```
Browser (WebSocket)
        │
        ▼
API Gateway WebSocket API
  $connect  ─────────────────────────────────────┐
  $disconnect ───────────────────────────────────│ ──► Lambda
  $default  ─────────────────────────────────────┘    (ck-agent-handler)
                                                           │
                          ┌────────────────────────────────┤
                          │                                │
                          ▼                                ▼
                  session_store.py               agent.py + tools.py
                  (DynamoDB r/w)                 (Bedrock converse_stream)
                          │                                │
               ┌──────────┤                     ┌──────────┤
               ▼          ▼                     ▼          ▼
         ck-sessions  ck-conversations    retrieve_    check_order_
          (PK: conn)   (PK: conv, SK:     knowledge    status
                        MSG#ts#uuid)          │
                                              ▼
                                    Bedrock Knowledge Base
                                    (S3 Vectors + Titan v2)
```

**AWS services used:** Lambda · API Gateway (WebSocket) · DynamoDB · Bedrock (Claude Haiku 4.5 + Knowledge Base) · S3 · CloudWatch · IAM

**Region:** `us-east-1`

---

## Repository Structure

```
.
├── src/ck_agent/
│   ├── agent.py            # converse_stream loop, system prompt, observability logging
│   ├── lambda_handler.py   # WebSocket route dispatcher ($connect/$disconnect/$default)
│   ├── session_store.py    # DynamoDB read/write for sessions and conversation history
│   ├── tools.py            # Tool definitions (TOOL_CONFIG) and dispatch logic
│   ├── verification.py     # Email/SSN/DOB validation, identity verification
│   ├── mock_data.py        # In-memory user and order data for demo
│   └── cli.py              # Local REPL for development testing
├── cdk/
│   ├── app.py              # CDK entry point, pinned to us-east-1
│   └── ck_agent_stack.py   # Lambda + API Gateway + DynamoDB + IAM definitions
├── frontend/
│   └── index.html          # Single-file WebSocket chat UI (deployed to GitHub Pages)
├── tests/
│   ├── conftest.py         # Integration test skip logic
│   ├── test_agent_stream.py
│   ├── test_session_store.py
│   ├── test_tools.py
│   └── test_verification.py
├── docs/
│   ├── observability.md           # Observability philosophy and log event schema
│   ├── observability_queries.md   # CloudWatch Logs Insights queries
│   ├── data_model_notes.md        # DynamoDB key schema rationale
│   └── rag_diagnostic.md          # RAG retrieval quality analysis
└── .github/workflows/
    ├── ci.yml              # Lint + test + cdk synth on every push/PR
    ├── deploy.yml          # CDK deploy to AWS on push to main (OIDC auth)
    └── pages.yml           # Publish frontend/ to GitHub Pages on push to main
```

---

## Core Components

### Agent Loop

`src/ck_agent/agent.py`

The agent uses Bedrock's `converse_stream` API in an agentic loop — capable of making multiple tool calls before producing a final response.

```
run_agent_stream(messages)
│
├── Call converse_stream with full message history + TOOL_CONFIG
│     │
│     ├── stream text_delta events → yield {"type": "text_delta", "text": "..."}
│     ├── stream tool_use_start   → yield {"type": "tool_use_start", "name": "..."}
│     └── stream end              → yield {"type": "end"}
│
├── If stop_reason == "tool_use":
│     ├── dispatch_tool(name, input) → result
│     ├── append tool result to messages
│     └── loop back to converse_stream
│
└── If stop_reason == "end_turn": yield {"type": "end"} and return
```

The loop is capped at 10 iterations to prevent runaway execution. Each event is forwarded to the browser over the WebSocket connection as it arrives, giving sub-second time-to-first-token.

**Model:** `global.anthropic.claude-haiku-4-5-20251001-v1:0`

---

### Tools

`src/ck_agent/tools.py`

Two tools are registered with the agent:

#### `retrieve_knowledge`

Queries the Bedrock Knowledge Base using semantic search and returns the top 5 most relevant chunks.

| Parameter | Type | Description |
|---|---|---|
| `query` | string | Search query derived from the user's question |

Returns formatted text chunks with relevance scores and source URIs.

#### `check_order_status`

Verifies the user's identity and returns order information.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `email` | string | ✅ | Must match `@ck<digits>.com` pattern |
| `ssn_last4` | string | ✅ | Exactly 4 digits |
| `dob_iso` | string | ✅ | Date of birth in `YYYY-MM-DD` |
| `selected_order_id` | string | ❌ | Specific order ID when user has multiple orders |

The tool calls `verify_user()` internally. If verification succeeds and the user has multiple orders, it returns an `orders_summary` list and sets `action_required: ask_user_to_select` — the agent then asks the user to choose and calls the tool again with `selected_order_id`.

---

### Identity Verification

`src/ck_agent/verification.py`

Three-field verification: email pattern + SSN last-4 + date of birth. All three must match.

**Email validation** — must match `^[a-zA-Z0-9._%+-]+@ck\d+\.com$`

**SSN extraction** — strips all non-digits, takes the last 4. Accepts `"1234"`, `"123-45-6789"`, `"my SSN is 6789"`, etc.

**DOB parsing** — two-stage:
1. **Fast path:** if input matches `YYYY-MM-DD`, return immediately (no API call)
2. **Slow path:** send to Bedrock Claude Haiku with a structured JSON prompt to handle natural language formats (`"March 15, 1990"`, `"15th of March 1990"`, etc.). Ambiguous numeric formats (e.g. `05/01/1990`) default to US convention (month first)

**Security:** error messages never reveal which field failed. Generic `"Verification details do not match our records"` prevents enumeration attacks.

---

### Session Persistence

`src/ck_agent/session_store.py`

Lambda is stateless — all session state lives in DynamoDB.

#### `ck-sessions` table

| Attribute | Type | Description |
|---|---|---|
| `connection_id` | PK (String) | API Gateway WebSocket connection ID |
| `conversation_id` | String | UUID linking to conversation history |
| `user_id` | String | Verified email once identity confirmed, else `"anonymous"` |
| `verification_state` | Map | Partial verification fields |
| `ttl` | Number | Epoch expiry — 2 hours from creation |

#### `ck-conversations` table

| Attribute | Type | Description |
|---|---|---|
| `conversation_id` | PK (String) | UUID |
| `sk` | SK (String) | `MSG#<timestamp_ms>#<uuid8>` — ensures chronological sort |
| `payload` | String | Full message JSON |
| `role` | String | `user` or `assistant` |
| `user_id` | String | For GSI attribution |
| `ttl` | Number | Epoch expiry — 90 days |

#### GSI: `by_user`

- **PK:** `user_id` — enables per-user history lookup after identity verification
- **SK:** `sk` — newest-first ordering via `ScanIndexForward=False`

**Session scope:** each WebSocket connection gets a fresh session. On `$connect`, `get_or_create_session()` checks for an existing record and loads message history if found. On `$disconnect`, the session record is deleted. This mirrors guest customer service — no cross-session tracking without login.

---

### Observability

`src/ck_agent/agent.py`, `src/ck_agent/lambda_handler.py`

Four structured JSON log events emitted to CloudWatch:

| Event | Fields | Emitted by |
|---|---|---|
| `route` | `route`, `connection_id` | `lambda_handler.py` on every WebSocket event |
| `turn_complete` | `duration_ms`, `input_tokens`, `output_tokens`, `stop_reason`, `conversation_id` | `agent.py` after each `converse_stream` call |
| `tool_invoked` | `tool_name`, `duration_ms`, `conversation_id` | `agent.py` after each tool dispatch |
| `verification_attempt` | `outcome` (success/failure), `failure_reason`, `conversation_id` | `agent.py` after `check_order_status` |

All events are queryable via CloudWatch Logs Insights. See `docs/observability_queries.md` for ready-to-run queries.

---

## Knowledge Base

The Bedrock Knowledge Base (`ck-kb-policies-and-10k`) is backed by an S3 bucket containing:

| Document | Description |
|---|---|
| `shipping_policy.md` | Synthetic shipping policy (standard, expedited, overnight, international, lost packages) |
| `return_policy.md` | Synthetic return policy (30-day window, electronics exception, refund timeline) |
| `amazon_10k_2019.pdf` | Amazon's 2019 annual report — used as a realistic source of company/financial information |

**Configuration:**
- Embeddings: Amazon Titan Text Embeddings v2 (1024 dimensions)
- Vector store: S3 Vectors (chosen over OpenSearch Serverless — saves ~$345/month idle cost)
- Chunking: Hierarchical (parent 1500 tokens / child 300 tokens / overlap 60 tokens)
- Parsing: Foundation model parsing via Nova Pro 1.0 (handles PDF tables correctly)
- Search: Semantic (vector similarity)

The KB is provisioned manually via AWS Console and referenced by ID (`BEDROCK_KB_ID`) — not managed by CDK.

---

## Infrastructure

`cdk/ck_agent_stack.py`

Managed by AWS CDK (Python). Deploys:

- **Lambda** — Python 3.13, 256 MB, 30s timeout, `lambda_dist/` as the package
- **API Gateway WebSocket API** — routes `$connect`, `$disconnect`, `$default` to Lambda
- **DynamoDB tables** — `ck-sessions` and `ck-conversations`, both pay-per-request with TTL enabled
- **IAM** — Lambda execution role with least-privilege policies for Bedrock, DynamoDB, and API Gateway management

```bash
cd cdk
cdk synth -c kb_id=<BEDROCK_KB_ID>   # preview CloudFormation
cdk deploy -c kb_id=<BEDROCK_KB_ID>  # deploy to AWS
```

The `lambda_dist/` directory is built fresh on CI using Linux-native wheels (required for `pydantic-core` binary compatibility with Lambda's Linux runtime).

---

## CI/CD

Three GitHub Actions workflows:

### `ci.yml` — runs on every push and PR

1. Lint with `ruff`
2. Run unit tests (`pytest -m "not integration"`)
3. Build `lambda_dist/` with Linux-native wheels
4. `cdk synth` — validates infrastructure compiles

### `deploy.yml` — runs on push to `main`

1. Authenticate to AWS via **OIDC** (no long-lived secrets stored)
2. Build `lambda_dist/`
3. `cdk deploy` — updates Lambda + API Gateway

### `pages.yml` — runs on push to `main` when `frontend/` changes

1. Upload `frontend/` as Pages artifact
2. Deploy to GitHub Pages

**OIDC setup:** GitHub Actions assumes `arn:aws:iam::810977966580:role/GitHubActionsDeployRole` via a short-lived token. No `AWS_ACCESS_KEY_ID` is stored anywhere.

---

## Testing

41 unit tests across 4 files. No real AWS calls — DynamoDB is mocked via `moto`, Bedrock via `unittest.mock`.

```bash
pytest tests -v -m "not integration"
```

| File | Tests | Coverage |
|---|---|---|
| `test_verification.py` | 17 | Email validation, SSN extraction, DOB parsing, verify_user |
| `test_tools.py` | 13 | Tool config shape, dispatch routing, all 4 mock users |
| `test_agent_stream.py` | 4 | Streaming events, tool_use loop, message list mutation |
| `test_session_store.py` | 7 | Session lifecycle, message persistence, reconnect, user_id update |

Integration tests (real AWS calls) are marked `@pytest.mark.integration` and skipped by default:

```bash
pytest tests -m integration   # requires real AWS credentials + deployed stack
```

---

## Local Development

```bash
# 1. Clone and set up environment
git clone https://github.com/mattp2003/cloudkinetics-assessment.git
cd cloudkinetics-assessment
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Set environment variables
echo "BEDROCK_KB_ID=<your_kb_id>" > .env

# 3. Run the CLI REPL (requires AWS credentials with Bedrock access)
python -m ck_agent.cli

# 4. Run tests
pytest tests -v -m "not integration"

# 5. Lint
ruff check src tests
```

---

## Deployment

### Prerequisites

- AWS account with Bedrock model access (Claude Haiku 4.5, Titan Text Embeddings v2)
- Bedrock Knowledge Base already provisioned (see [Knowledge Base](#knowledge-base))
- Node.js 20+ (for CDK CLI)
- AWS CDK: `npm install -g aws-cdk`

### Steps

```bash
# Bootstrap CDK (first time only)
cd cdk
cdk bootstrap

# Build Lambda package
pip install boto3 pydantic python-dateutil -t lambda_dist/
cp -r ../src/ck_agent lambda_dist/

# Deploy
cdk deploy -c kb_id=<BEDROCK_KB_ID>
```

The deploy outputs the WebSocket URL. Update `frontend/index.html` with the new URL if it changes.

### Teardown

```bash
cd cdk && cdk destroy
# Then manually delete: Bedrock KB, S3 buckets, CDKToolkit CloudFormation stack
```

---

## Environment Variables

| Variable | Where | Description |
|---|---|---|
| `BEDROCK_KB_ID` | Lambda env (set by CDK) | Bedrock Knowledge Base ID |
| `CONVERSATIONS_TABLE` | Lambda env (set by CDK) | DynamoDB conversations table name |
| `SESSIONS_TABLE` | Lambda env (set by CDK) | DynamoDB sessions table name |
| `AWS_DEFAULT_REGION` | CI / Lambda runtime | Must be `us-east-1` |

---

## Mock Users

The demo uses in-memory mock data. No real database backend.

| Email | SSN last-4 | DOB | Orders |
|---|---|---|---|
| `alice@ck1.com` | `6789` | `1990-03-15` | 3 (Delivered, Shipped, Processing) |
| `bob@ck2.com` | `4321` | `1985-07-22` | 1 (Out for Delivery) |
| `carol@ck123.com` | `9123` | `1995-11-05` | 0 |
| `dan@ck5.com` | `4987` | `1988-04-30` | 2 (Delayed, Delivered) |

---

## Design Decisions

| Decision | Rationale |
|---|---|
| WebSocket over REST | Enables real-time token streaming. REST would require client polling |
| `converse_stream` over `converse` | Sub-second time-to-first-token vs 3–5s wait for full response |
| DynamoDB over RDS | No connection pool management with Lambda; TTL built-in; pay-per-request matches bursty traffic |
| S3 Vectors over OpenSearch Serverless | OpenSearch Serverless costs ~$345/month minimum (2 OCU floor). S3 Vectors costs <$1/month at this scale |
| Hierarchical chunking | Preserves section context for policy documents; child chunks retrieved for precision, parent context returned for coherence |
| DOB parsed by LLM | Users express dates in many formats. Regex/dateutil can't reliably handle natural language; LLM handles it with a fast-path bypass for already-ISO inputs |
| OIDC over IAM access keys | No credentials to store, rotate, or leak. GitHub requests a short-lived token from AWS at deploy time |
| Single Lambda handler | `requestContext.routeKey` cleanly routes `$connect`/`$disconnect`/`$default` without needing separate functions |
| `us-east-1` | Best Bedrock model availability; consistent region for all services |

---

## Known Limitations

- **No cross-session continuity** — context is scoped to a single WebSocket connection. Reconnecting starts a fresh session. No login system means no persistent user identity.
- **Mock data only** — order and user data is in-memory. No real order database backend.
- **No rate limiting** — the WebSocket endpoint has no WAF or throttling beyond API Gateway defaults.
- **US date bias** — ambiguous numeric DOB formats (e.g. `05/01/1990`) are interpreted as month-first (US convention).
- **DOB latency** — the first verification turn calls Bedrock to parse the date of birth (~500ms extra) unless the user provides ISO format directly.
