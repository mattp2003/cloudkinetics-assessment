# Phase 06 — RAG Diagnostic

## Prerequisites

- [ ] Phase 05 complete (KB synced and working)
- [ ] Agent answers at least one 10-K question and one policy question

## Goal

Run a structured set of probe queries against the Knowledge Base, capture retrieval quality for each, and produce evidence (screenshots + a markdown table) you'll use in the Level 300 preprocessing section of your design doc on Sunday.

**This is the single highest-leverage 45 minutes of the weekend** — it turns a generic "I designed a pipeline" into a concrete "I diagnosed these 3 failures and designed fixes."

## Context for Claude Code

- This phase produces artifacts, not code. The deliverable is `docs/rag_diagnostic.md`
- Each probe is a query + expected behavior + actual result + analysis
- Some queries SHOULD work (to show what's going right); some should expose failures (to motivate the pipeline in the design doc)
- You are NOT trying to fix retrieval in this phase — just document it

## Steps

### 6.1 — Set up the probe harness

Create `scripts/rag_probe.py`:

```python
"""Quick probe script — runs a set of queries against the KB and dumps results."""
import json
import os
from pathlib import Path

from ck_agent.cli import _load_env
_load_env()
from ck_agent.tools import retrieve_knowledge, BEDROCK_AGENT_RUNTIME, KB_ID

PROBES = [
    {
        "id": "P1",
        "query": "What is your return policy?",
        "expected": "Should retrieve from return_policy.md — tests synthetic doc",
        "category": "policy_faq",
    },
    {
        "id": "P2",
        "query": "How many employees did Amazon have at the end of 2019?",
        "expected": "Should retrieve Item 1 Employees section from 10-K page 4 (answer: 798,000)",
        "category": "factual_specific",
    },
    {
        "id": "P3",
        "query": "What were Amazon's net sales in 2019?",
        "expected": "Should retrieve Item 6 financial table from 10-K page 18 (answer: $280,522 million)",
        "category": "tabular_data",
    },
    {
        "id": "P4",
        "query": "What are Amazon's risks related to operations in China?",
        "expected": "Should retrieve the PRC/India paragraph from Item 1A page 8",
        "category": "targeted_semantic",
    },
    {
        "id": "P5",
        "query": "What are the risks if Amazon cannot hire enough software engineers?",
        "expected": "Should retrieve 'Loss of Key Senior Management' section from page 10",
        "category": "targeted_semantic",
    },
    {
        "id": "P6",
        "query": "How does expedited shipping work?",
        "expected": "Should retrieve from shipping_policy.md",
        "category": "policy_faq",
    },
    {
        "id": "P7",
        "query": "material adverse effect",
        "expected": "Ambiguous phrase — tests embedding collision on boilerplate. Will likely return many chunks, low precision.",
        "category": "diagnostic_negative",
    },
]

def run_probe(probe):
    resp = BEDROCK_AGENT_RUNTIME.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": probe["query"]},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": 5, "overrideSearchType": "HYBRID"}
        },
    )
    results = []
    for r in resp.get("retrievalResults", []):
        results.append({
            "score": r.get("score"),
            "source": r.get("location", {}).get("s3Location", {}).get("uri", "?").split("/")[-1],
            "text_preview": r["content"]["text"][:200].replace("\n", " "),
        })
    return results


def main():
    out_dir = Path("docs")
    out_dir.mkdir(exist_ok=True)
    all_results = []
    for probe in PROBES:
        print(f"\n=== {probe['id']}: {probe['query']} ===")
        results = run_probe(probe)
        for i, r in enumerate(results, 1):
            print(f"  [{i}] score={r['score']:.3f} src={r['source']}")
            print(f"      {r['text_preview']}...")
        all_results.append({**probe, "results": results})

    # Dump raw results for design-doc writing
    (out_dir / "rag_diagnostic_raw.json").write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved raw results to docs/rag_diagnostic_raw.json")


if __name__ == "__main__":
    main()
```

### 6.2 — Run the probes

```bash
python scripts/rag_probe.py | tee docs/rag_diagnostic_run.log
```

### 6.3 — Analyze & write `docs/rag_diagnostic.md`

Create a structured markdown file with this template:

```markdown
# RAG Retrieval Diagnostic

Run date: <YYYY-MM-DD>
Knowledge Base ID: <KB_ID>
Config: Foundation-model parsing (Claude Sonnet 4.6 or whichever model you selected in phase 05) + hierarchical chunking (parent 1500 / child 300 / overlap 60) + Titan Embeddings v2 + Hybrid search, top 5

## Summary

| Probe | Query | Retrieval quality | Failure mode (if any) |
|-------|-------|-------------------|----------------------|
| P1 | Return policy | ✅ Good | — |
| P2 | Employee count | [fill in] | [fill in] |
| P3 | Net sales 2019 | [fill in] | [fill in] |
| P4 | China operations risks | [fill in] | [fill in] |
| P5 | Software engineer hiring risks | [fill in] | [fill in] |
| P6 | Expedited shipping | ✅ Good | — |
| P7 | "material adverse effect" | [expected: high noise] | [fill in] |

## Detailed findings

### P1 — ...
Query: "..."
Expected: ...
Retrieved:
1. [score] source — preview
2. ...
Analysis: Hit / miss / partial. What the embedding "thought" the query meant.

(repeat for each probe)

## Failure patterns identified

1. **[If observed] Tabular data mangling** — P3 retrieved garbled numbers / missed the table entirely. Root cause: [describe].
2. **[If observed] Boilerplate embedding collision** — P7 retrieved 5 chunks all containing the phrase, none semantically distinct.
3. **[If observed] Section-boundary splitting** — P4 retrieved first half of PRC discussion without the India continuation.
4. ...

## Proposed fixes (for design doc)

For each failure pattern above, propose a concrete pipeline step:

- **Fix for tabular data**: Use Textract AnalyzeDocument with TABLES feature during preprocessing, serialize tables as key-value text chunks with column-wise context, tag with metadata `content_type=table`.
- **Fix for boilerplate collision**: Add query-side rewriting (expand abbreviations, add document-section context). Add cross-encoder reranking post-retrieval.
- **Fix for section-boundary splitting**: Already partially mitigated by hierarchical chunking. Next step: semantic chunking with section-header detection for 10-K style documents.
- ...

## Screenshots

- `docs/screenshots/rag_p3_tables.png` — showing table retrieval result
- `docs/screenshots/rag_p7_collision.png` — showing duplicate boilerplate chunks
```

### 6.4 — Take screenshots

For each probe that illustrates an interesting failure, take a screenshot. You have two options:

**Option A — AWS Console Knowledge Base "Test" tab:** Navigate to Bedrock → your KB → Test. Run the query, screenshot the retrieved chunks panel on the right.

**Option B — Terminal output:** Screenshot the `rag_probe.py` output for that query.

Save to `docs/screenshots/`. Commit these to the repo.

### 6.5 — Write 2-3 sentence commentary per probe directly in `rag_diagnostic.md`

Be specific. Don't write "the result was bad" — write "the retrieved chunk contained the word 'engineers' but was about supplier engineering, not internal hiring — semantic miss despite keyword match."

## Verification (human-runnable)

```bash
# The probe script runs end-to-end
python scripts/rag_probe.py
# Expected: 7 probes run, each prints 5 results

# The diagnostic doc exists and has content for all probes
wc -l docs/rag_diagnostic.md
# Expected: 80+ lines

# At least 2 screenshots captured
ls docs/screenshots/ | wc -l
# Expected: >= 2
```

## Definition of Done

- [ ] `scripts/rag_probe.py` runs clean with no errors
- [ ] `docs/rag_diagnostic_raw.json` saved (machine-readable)
- [ ] `docs/rag_diagnostic.md` has a complete table + detailed findings
- [ ] At least 2 screenshots in `docs/screenshots/`
- [ ] At least ONE real failure pattern identified and documented — even if the KB works great for most queries, find the weakest probe and analyze it honestly

## Out of Scope

- ❌ Actually fixing retrieval quality — design doc only
- ❌ Building a reranker or query rewriter
- ❌ Running evals at scale (evals framework discussed in doc only)
- ❌ Comparing multiple KB configurations side-by-side (would take hours)

## Commit Message

```
[phase 06] RAG diagnostic with structured probes

- scripts/rag_probe.py: 7 probes covering policy lookup, factual recall,
  tabular data, semantic targeting, and boilerplate collision
- docs/rag_diagnostic.md: analysis of each probe with failure-pattern taxonomy
- docs/rag_diagnostic_raw.json: machine-readable results
- Screenshots in docs/screenshots/ for design-doc inclusion
- Reference: plans/06_rag_diagnostic.md
```
