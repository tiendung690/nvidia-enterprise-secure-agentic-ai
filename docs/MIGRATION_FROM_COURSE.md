# Migration from the Educative course repositories

## Removed

- Groq integration.
- `OllamaEmbedding` and all Ollama configuration.
- Hard-coded API placeholders.
- Index rebuild on every query/application boot.
- Dead code after `return` in `rag_tool.py`.
- Unsafe calculator `eval()` pattern from the assessment.
- Raw `verbose=True` reasoning output in the public API.

## Added

- NVIDIA OpenAI-compatible LLM through LlamaIndex `OpenAILike`.
- NVIDIA hosted embedding adapter implementing LlamaIndex `BaseEmbedding`.
- Persisted `VectorStoreIndex` storage.
- Docker image and Docker Compose host workflow.
- FunctionAgent production mode and ReActAgent course mode.
- FastAPI, health endpoints, metrics, timeout, prompt guard, and admin-protected ingestion.
- Direct chat/embedding smoke scripts.
- Unit and optional live tests.
