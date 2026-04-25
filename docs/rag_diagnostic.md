# RAG Retrieval Diagnostic

**Run date:** 2026-04-26  
**Knowledge Base ID:** Z5R2V3S1ZK  
**Config:** Nova Pro 1.0 FM parsing + hierarchical chunking (parent 1500 / child 300 / overlap 60) + Amazon Titan Text Embeddings v2 + SEMANTIC search, top 5 results

---

## Summary

| Probe | Category | Query | Retrieval quality | Failure mode |
|-------|----------|-------|-------------------|--------------|
| P1 | policy_faq | Return policy | ✅ Good | — |
| P2 | factual_specific | Employee count 2019 | ⚠️ Partial | Correct doc retrieved, wrong chunk — employee figure not in top result |
| P3 | tabular_data | Net sales 2019 | ❌ Miss | Table of Contents chunk retrieved instead of financial data |
| P4 | targeted_semantic | China operations risks | ✅ Good | Correct risk section retrieved |
| P5 | targeted_semantic | Software engineer hiring risks | ⚠️ Partial | Adjacent risk sections retrieved, not the exact talent section |
| P6 | policy_faq | Expedited shipping | ✅ Good | — |
| P7 | diagnostic_negative | "material adverse effect" | ⚠️ Boilerplate collision | Multiple dissimilar risk chunks returned at similar scores |

---

## Detailed Findings

### P1 — Return Policy
**Query:** "What is your return policy?"  
**Expected:** return_policy.md  
**Top result:** score=0.494, src=return_policy.md  
**Analysis:** Hit. The synthetic markdown doc retrieves cleanly as the top result with a healthy score gap over the second result (0.494 vs 0.403). The 10-K chunks at positions 2 and 3 are semantic noise — they contain the word "policies" but in an unrelated context (marketplace seller policies). This is expected cross-document bleed at lower relevance scores and does not affect answer quality since the top result is correct.

---

### P2 — Employee Count 2019
**Query:** "How many employees did Amazon have at the end of 2019?"  
**Expected:** 10-K Item 1 Employees section (answer: 798,000)  
**Top result:** score=0.465, src=Company-10k-18pages.pdf (Content Creators / Competition section)  
**Analysis:** Partial. The correct document (10-K) is retrieved but the wrong chunk — the top 3 results all land in the Table of Contents / Business overview section, not the Employees paragraph. The 798,000 figure does appear when querying "Amazon full-time employees worldwide" (verified separately), meaning the chunk exists in the index but the embedding for the question-style query does not rank it highly. **Root cause:** The employee count paragraph is brief (~3 sentences) and competes against longer, denser sections that share topical vocabulary ("Amazon", "2019", "operations"). Hierarchical chunking helps but the parent chunk boundary may span the employee paragraph together with unrelated content, diluting its embedding.

---

### P3 — Net Sales 2019 (Tabular Data)
**Query:** "What were Amazon's net sales in 2019?"  
**Expected:** Financial table from 10-K page 18 ($280,522 million)  
**Top result:** score=0.429, src=Company-10k-18pages.pdf (Table of Contents index page)  
**Analysis:** Miss. The Table of Contents chunk is retrieved as the top result — it contains the phrase "net sales" only as a section header reference. The actual financial data table on page 18 does not surface in top 5. **Root cause:** Financial tables in PDFs, even with FM parsing, are often serialized as rows of numbers without sufficient surrounding prose context. The embedding for "$280,522 million" or "net sales 2019" does not match well against a question phrased in natural language. This is the clearest failure mode in this diagnostic and the strongest motivation for a dedicated table-preprocessing pipeline.

---

### P4 — China Operations Risks
**Query:** "What are Amazon's risks related to operations in China?"  
**Expected:** PRC/India paragraph from Item 1A  
**Top result:** score=0.500, src=Company-10k-18pages.pdf (international operations risk factors)  
**Analysis:** Hit. The highest-scoring result across all probes (0.500). The retrieved chunk covers international operational risks including "lower levels of use of the Internet", "lower levels of credit card usage", "difficulty in staffing foreign operations" — this is the correct Item 1A section. The query is specific and the document has rich, distinct prose for this topic, giving the embedding a clear signal.

---

### P5 — Software Engineer Hiring Risks
**Query:** "What are the risks if Amazon cannot hire enough software engineers?"  
**Expected:** Loss of Key Senior Management / competition for technical staff section  
**Top result:** score=0.441, src=Company-10k-18pages.pdf (M&A integration risks)  
**Analysis:** Partial. The query did not retrieve the talent/hiring risk section directly. Instead it retrieved chunks about M&A integration difficulties and international staffing challenges — these share semantic similarity ("staffing", "difficulty", "operations") but are not the target section. The exact talent-hiring risk section uses language like "competition for qualified personnel" and "software engineers, computer scientists" — a query using those terms retrieves the section directly (verified in Phase 05). **Root cause:** Question-style queries ("what are the risks if...") embed differently from the declarative risk language in the document. This motivates query rewriting as a preprocessing step.

---

### P6 — Expedited Shipping
**Query:** "How does expedited shipping work?"  
**Expected:** shipping_policy.md  
**Top result:** score=0.488, src=shipping_policy.md  
**Analysis:** Hit. Clean retrieval from the synthetic policy doc. The score gap between the top result (0.488) and the 10-K noise at position 2 (0.392) is comfortable. The shipping policy markdown structure chunks well because each section is self-contained and topically distinct.

---

### P7 — Boilerplate Collision ("material adverse effect")
**Query:** "material adverse effect"  
**Expected:** High noise — boilerplate phrase appearing across many unrelated risk clauses  
**Top result:** score=0.422, src=Company-10k-18pages.pdf (legal proceedings section)  
**Analysis:** As predicted, the phrase "material adverse effect" is a legal boilerplate term used throughout the 10-K Risk Factors section. All 3 retrieved chunks are from different risk subsections (legal proceedings, M&A, digital rights management) with similar scores (0.422, 0.377, 0.376) — a flat score distribution indicating low discrimination. No single chunk is "the right answer" because the phrase has no unique semantic anchor in the document. **Root cause:** Boilerplate legal phrases create embedding collisions — many chunks encode the same surface-level semantics. This demonstrates why keyword-level queries degrade retrieval quality.

---

## Failure Patterns Identified

### 1. Tabular Data Misrepresentation (P3)
Financial tables in the 10-K are not retrievable via natural language questions about their content. The table chunks either lack surrounding prose context or the FM parser serialized them without column-header associations, making the embeddings semantically weak.

**Proposed fix:** Pre-process PDFs with Amazon Textract `AnalyzeDocument` (TABLES feature). Serialize each table row as `"[metric]: [value] (year: YYYY)"` text chunks. Tag with metadata `content_type=table`, `page=N`. Apply metadata filtering at query time for financial questions.

### 2. Query-Document Language Mismatch (P2, P5)
Question-style queries ("how many...", "what are the risks if...") embed differently from the declarative prose in the document. The correct chunk exists in the index but ranks below unrelated chunks with stronger surface-level overlap.

**Proposed fix:** Add a query rewriting step before retrieval — use a lightweight LLM call to expand the question into declarative search terms (e.g. "How many employees?" → "Amazon full-time part-time employees December 2019 headcount"). This is a standard RAG pre-retrieval enhancement.

### 3. Boilerplate Embedding Collision (P7)
High-frequency legal phrases appear in dozens of risk factor paragraphs, causing flat score distributions where multiple irrelevant chunks score equally.

**Proposed fix:** Add a cross-encoder reranker (e.g. Cohere Rerank via Bedrock) as a post-retrieval step to re-score the top-5 chunks against the original query with a more discriminative model. Also consider filtering out chunks where the query term appears purely as syntactic boilerplate (frequency-based heuristic).

### 4. Short Fact Embedding Dilution (P2)
Very short factual passages (the 3-sentence employee count paragraph) are diluted when co-chunked with longer, denser surrounding sections. The parent chunk's embedding is dominated by the majority content.

**Proposed fix:** Semantic chunking with section-boundary detection for structured documents like 10-Ks. Detect section headers (bold, all-caps, numbered) and force chunk boundaries at section transitions regardless of token count.

---

## Screenshots

Take screenshots of P3 (table miss) and P7 (boilerplate collision) from the Bedrock console KB Test tab and save to `docs/screenshots/` for the design doc.

Recommended screenshots:
- `docs/screenshots/rag_p3_net_sales_miss.png` — showing ToC chunk retrieved instead of financial data
- `docs/screenshots/rag_p7_boilerplate_collision.png` — showing flat scores across dissimilar chunks
