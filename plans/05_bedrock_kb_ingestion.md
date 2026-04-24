# Phase 05 — Bedrock Knowledge Base Ingestion

## Prerequisites

- [ ] Phase 04 complete (local agent working with stub retrieve_knowledge)
- [ ] AWS account has Bedrock model access for Titan Text Embeddings v2
- [ ] OpenSearch Serverless service available in us-east-1 (check account quotas)

## Goal

A Bedrock Knowledge Base synced with two document types: the provided Amazon 10-K PDF and 2 synthetic company policy docs. The stub `retrieve_knowledge` in `tools.py` is replaced with a real `bedrock-agent-runtime.retrieve` call.

## Context for Claude Code

- We are using the AWS Console for the KB setup because Bedrock KB CDK support is fiddly and console is faster for one-time setup — this is a deliberate time-saving choice
- The CDK stack in phase 07 will reference the KB by ID as an input parameter; it will NOT try to create it
- Two synthetic docs need to be created: `shipping_policy.md` and `return_policy.md`
- S3 bucket name: `ck-knowledge-docs-<your_account_id>` (use AWS CLI to find account ID)

## Steps

### 5.1 — Create synthetic policy documents

Place these in `docs/kb_source/`. Claude Code can write them directly.

**`docs/kb_source/shipping_policy.md`** (~300 words):
- Standard shipping: 5-7 business days, free over $50
- Expedited: 2-3 business days, $12.99 flat
- Overnight: $24.99, orders placed before 2pm PST ship same day
- International: select countries only, 10-21 business days
- Tracking: emailed when label is printed, updates in real-time
- Lost packages: contact customer service after 10 business days beyond estimated delivery
- APO/FPO addresses: supported, 14-30 business days

**`docs/kb_source/return_policy.md`** (~300 words):
- 30-day return window from delivery date
- Items must be unused, in original packaging
- Free returns for defective items; $5.99 label fee otherwise
- Electronics: 15-day window (stricter)
- Final sale items: marked as such at checkout, not returnable
- Refund timeline: 5-7 business days after warehouse receipt
- How to start: email support with order ID and reason

**`docs/kb_source/amazon_10k_2019.pdf`**: copy the uploaded 10-K here.

### 5.2 — Upload to S3

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="ck-knowledge-docs-${ACCOUNT_ID}"
REGION="us-east-1"

aws s3 mb "s3://${BUCKET}" --region ${REGION}
aws s3 cp docs/kb_source/ "s3://${BUCKET}/" --recursive
aws s3 ls "s3://${BUCKET}/"
# Expected: 3 files listed
```

Save the bucket name — you'll need it in the console.

### 5.3 — Create the Knowledge Base in AWS Console

Navigate to: `Bedrock` → `Knowledge Bases` → `Create knowledge base`.

**Step 1 — Knowledge base details:**
- Name: `ck-kb-policies-and-10k`
- IAM role: Create and use a new service role (default)

**Step 2 — Data source:**
- Name: `ck-docs-s3`
- Data source location: S3 → `s3://ck-knowledge-docs-<account_id>/`
- **Parsing strategy:** *Foundation models for parsing* → select the most current Claude offered by the KB dropdown (at time of writing: Sonnet 4.6 or Sonnet 4.5 depending on region). **This is critical for the 10-K tables.** Cost: a few cents per 18-page PDF. Acceptable for the assessment.
- **Chunking strategy:** *Hierarchical chunking*
  - Parent chunk max tokens: 1500
  - Child chunk max tokens: 300
  - Overlap tokens: 60

**Step 3 — Embeddings and vector store:**
- Embeddings model: *Amazon Titan Text Embeddings v2* (1024 dimensions)
- Vector database: *Quick create a new vector store* → OpenSearch Serverless (this provisions everything for you; takes ~5 min)

**Step 4 — Review and create.** Click create.

**Wait for the KB status to become "Available" (~3-5 min), then click "Sync" on the data source.** Sync takes ~5-10 min for these 3 docs.

### 5.4 — Capture the KB ID

Once created, copy the Knowledge Base ID (looks like `ABC123XYZ0`). Save it to a local file:

```bash
echo "BEDROCK_KB_ID=<your_kb_id>" >> .env
```

Add `.env` to `.gitignore` (already done in phase 01). This ID will be baked into the CDK stack in phase 07 as a context variable.

### 5.5 — Replace the stub in `tools.py`

```python
import os
import boto3

BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
KB_ID = os.environ.get("BEDROCK_KB_ID", "")

def retrieve_knowledge(query: str) -> str:
    """Retrieve relevant passages from the Bedrock Knowledge Base."""
    if not KB_ID:
        return "[ERROR: BEDROCK_KB_ID not set in environment]"

    response = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 5,
                "overrideSearchType": "HYBRID",  # vector + keyword
            }
        },
    )

    results = response.get("retrievalResults", [])
    if not results:
        return "No relevant information found in the knowledge base for this query."

    # Format retrieved chunks into a string the LLM can use
    formatted = []
    for i, r in enumerate(results, 1):
        text = r["content"]["text"]
        source = r.get("location", {}).get("s3Location", {}).get("uri", "unknown")
        score = r.get("score", 0)
        formatted.append(f"[{i}] (relevance: {score:.2f}, source: {source})\n{text}")

    return "\n\n---\n\n".join(formatted)
```

### 5.6 — Load `.env` in CLI

Add to `src/ck_agent/cli.py`:
```python
from pathlib import Path

def _load_env():
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                import os
                os.environ.setdefault(k.strip(), v.strip())

# Call at top of main()
```

Or use `python-dotenv` as a dep if preferred (add to `pyproject.toml`).

## Verification (human-runnable)

```bash
# KB is accessible
aws bedrock-agent list-knowledge-bases --region us-east-1 --query "knowledgeBaseSummaries[].[knowledgeBaseId, name, status]"
# Expected: your KB listed with status ACTIVE

# Retrieve works directly via CLI
source .env  # or export BEDROCK_KB_ID=...
aws bedrock-agent-runtime retrieve \
  --knowledge-base-id $BEDROCK_KB_ID \
  --retrieval-query '{"text":"what is the return policy"}' \
  --region us-east-1
# Expected: retrievalResults array with at least 1 hit from return_policy.md

# Integration through Python
python -c "
from ck_agent.cli import _load_env; _load_env()
from ck_agent.tools import retrieve_knowledge
print(retrieve_knowledge('return policy')[:300])
"
# Expected: actual policy text from your synthetic doc

# Agent loop uses real KB now
python -m ck_agent.cli
# Ask: "what is your return policy?"
# Expected: answer cites actual details from return_policy.md
```

## Definition of Done

- [ ] S3 bucket contains 3 source documents
- [ ] Bedrock KB status = Available, data source synced with all 3 docs
- [ ] `BEDROCK_KB_ID` saved in `.env`
- [ ] `retrieve_knowledge` calls real KB and returns real text
- [ ] Agent answers "what is your return policy?" with content from synthetic doc
- [ ] Agent answers "how many employees does Amazon have?" with content from 10-K (tests 10-K ingestion)

## Out of Scope

- ❌ CDK automation of KB creation (console is fine for now)
- ❌ Reranking / hybrid search optimization beyond enabling HYBRID mode
- ❌ Running the diagnostic queries (that's phase 06)
- ❌ Metadata filtering (discussed in design doc, not implemented)

## Commit Message

```
[phase 05] Bedrock Knowledge Base ingestion

- Two synthetic policy docs (shipping, returns) + Amazon 10-K PDF
- S3 bucket ck-knowledge-docs-<account_id>
- Bedrock KB with foundation-model parsing (handles 10-K tables)
  and hierarchical chunking (preserves section structure)
- OpenSearch Serverless vector store, Titan Embeddings v2
- retrieve_knowledge now calls real KB via bedrock-agent-runtime
- Hybrid search (vector + keyword) for better term matching
- Reference: plans/05_bedrock_kb_ingestion.md
```
