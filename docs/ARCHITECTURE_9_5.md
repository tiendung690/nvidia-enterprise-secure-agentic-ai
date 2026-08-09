# Agentic RAG architecture — SSE/TL to TA/SA 9.5/10

## Architectural thesis

An enterprise Agentic RAG system is not “an LLM with functions.” It is a controlled decision-and-execution runtime with:

- isolated knowledge boundaries,
- typed capabilities,
- deterministic budgets and authorization,
- provenance and citation verification,
- versioned state/cache,
- observability and evaluation gates.

## Control plane versus data plane

### Control plane

- `AgentService`: deadline, concurrency, session, cache, tool budget, event collection.
- `FunctionAgent`/`ReActAgent`: probabilistic planning and tool selection.
- system prompt: routing, grounding, citation, and safety behavior.
- citation validator: deterministic postcondition.

### Data plane

- NVIDIA Nemotron chat completion.
- NVIDIA query/passage embeddings.
- corpus-specific persisted vector indexes.
- read-only external tools.

This separation is important: the LLM proposes actions, while deterministic code enforces budgets, source contracts, cache isolation, and validation.

## Retrieval architecture

Course lessons and research papers are separate indexes and separate tools. This avoids a dense-retrieval failure where research-survey chunks with high “RAG” keyword density crowd out explicit course definitions.

```text
Course query  -> agentic_rag_course_tool  -> course_index
Paper query   -> research_paper_rag_tool  -> papers_index
```

Retrieval is evidence-only:

```text
query -> query embedding -> candidate retrieval -> score filter -> top-k evidence
      -> structured sources -> one agent synthesis
```

It deliberately avoids:

```text
agent LLM -> QueryEngine LLM -> agent LLM
```

which caused nested generation, higher cost, weaker provenance, and 75–151 second traces in earlier iterations.

## Provenance model

Each node receives a deterministic ID:

```text
corpus:relative-file:chunk-index:content-hash
```

Each retrieved source exposes:

- stable source ID,
- stable citation ID,
- corpus and file,
- page/section/chunk index,
- similarity score,
- evidence excerpt,
- indirect-injection signals.

The agent must cite claims using the IDs supplied in evidence. Post-generation validation checks unknown IDs and citation coverage. Invalid grounded answers are not cached; strict mode rejects them.

## Cache correctness

Cache key dimensions:

```text
user + session + normalized query + index version
+ model + temperature + top_p + reasoning budget + max tokens
+ agent mode + direct/indirect guard policy
+ citation mode/coverage + prompt version
```

This prevents reuse after data, prompt, model, or generation-policy changes and prevents cross-user session collisions.

## Failure handling

- Queue timeout: protects overload.
- Request deadline: bounds long agent loops.
- Tool-call budget: bounds cost and loops deterministically.
- Same-tool-call budget: detects repeated failed retrieval.
- Provider classifier: maps NVIDIA capacity errors to 503 and Retry-After.
- Atomic index build/swap: preserves the previous valid index after ingestion failure.
- Runtime ingestion clears response cache and returns `restart_required=true`; existing agent
  tools remain bound to startup retrievers until the application restarts.
- Citation gate: prevents unsupported grounded answers from entering cache.

## Scale path

### Current reference

One API process, local persisted index, in-memory session/cache.

### Production evolution

1. API Gateway/WAF + OIDC/JWT.
2. Tenant-aware policy and ACL metadata filters.
3. Redis for response cache and conversation state.
4. Managed vector database with hybrid retrieval and reranking.
5. Durable workflow engine for long-running agents.
6. OpenTelemetry traces and SLO dashboards.
7. Golden-evaluation CI, canary release, rollback.

## Main trade-offs

- Smaller chunks improve embedding safety and citation precision but may reduce context completeness.
- Higher top-k improves recall but increases context cost/noise; candidate retrieval plus threshold provides a balance.
- Strict citation validation improves trust but may reject useful answers when the model formats citations poorly.
- Session-scoped cache maximizes isolation; shared semantic cache improves reuse but requires tenant and permission-aware keys.
