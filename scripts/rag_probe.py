"""Quick probe script — runs a set of queries against the KB and dumps results."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck_agent.cli import _load_env
_load_env()

import boto3

KB_ID = os.environ.get("BEDROCK_KB_ID", "")
BEDROCK_AGENT_RUNTIME = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

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
        "expected": "Should retrieve financial table from 10-K page 18 (answer: $280,522 million)",
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
            "vectorSearchConfiguration": {"numberOfResults": 5, "overrideSearchType": "SEMANTIC"}
        },
    )
    results = []
    for r in resp.get("retrievalResults", []):
        results.append({
            "score": round(r.get("score", 0), 4),
            "source": r.get("location", {}).get("s3Location", {}).get("uri", "?").split("/")[-1],
            "text_preview": r["content"]["text"][:300].replace("\n", " "),
        })
    return results


def main():
    if not KB_ID:
        print("ERROR: BEDROCK_KB_ID not set. Create a .env file with BEDROCK_KB_ID=<id>")
        sys.exit(1)

    out_dir = Path("docs")
    out_dir.mkdir(exist_ok=True)
    all_results = []

    for probe in PROBES:
        print(f"\n{'='*70}")
        print(f"{probe['id']} [{probe['category']}]: {probe['query']}")
        print(f"Expected: {probe['expected']}")
        print(f"{'-'*70}")
        results = run_probe(probe)
        for i, r in enumerate(results, 1):
            print(f"  [{i}] score={r['score']:.4f}  src={r['source']}")
            print(f"      {r['text_preview']}...")
        all_results.append({**probe, "results": results})

    (out_dir / "rag_diagnostic_raw.json").write_text(json.dumps(all_results, indent=2))
    print(f"\n{'='*70}")
    print(f"Saved raw results to docs/rag_diagnostic_raw.json")


if __name__ == "__main__":
    main()
