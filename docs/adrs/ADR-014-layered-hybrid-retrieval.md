# ADR-014: Layered hybrid retrieval

**Decision:** compose guarded multi-query, vector + lexical retrieval, RRF, deterministic rerank and
a bounded corrective fallback.

**Why:** exact identifiers and semantic paraphrases fail differently. BM25 and cosine scores are not
on the same scale, so rank fusion is safer than raw weighted addition. The quality evaluator returns
a tier rather than asking the model to interpret uncalibrated raw scores.

**Consequence:** local BM25 is suitable for reference/small corpus. Production scale needs a managed
lexical/vector engine with metadata prefilter and measured calibration.
