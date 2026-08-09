from __future__ import annotations

from typing import Any

from nvidia_agentic_rag.config import Settings


def _build_openai_like(
    settings: Settings,
    *,
    model: str,
    max_tokens: int,
    enable_thinking: bool,
    configured_context_window: int | None = None,
) -> Any:
    try:
        from llama_index.llms.openai_like import OpenAILike
    except ImportError as exc:  # pragma: no cover - dependency error is environment-specific
        raise RuntimeError(
            "Install llama-index-llms-openai-like before starting the application"
        ) from exc

    extra_body: dict[str, Any] = {
        "chat_template_kwargs": {
            "enable_thinking": enable_thinking,
            # NVIDIA's model card requires this for reliable reasoning + tool-call parsing.
            "force_nonempty_content": settings.nvidia_force_nonempty_content,
            "medium_effort": settings.nvidia_medium_effort,
        }
    }
    if enable_thinking:
        extra_body["reasoning_budget"] = settings.nvidia_reasoning_budget

    effective_context_window = settings.effective_llm_context_window(
        model=model,
        max_tokens=max_tokens,
        configured=configured_context_window,
    )

    return OpenAILike(
        model=model,
        api_base=settings.nvidia_base_url,
        api_key=settings.api_key_value(),
        context_window=effective_context_window,
        is_chat_model=True,
        is_function_calling_model=True,
        temperature=settings.nvidia_temperature,
        max_tokens=max_tokens,
        timeout=settings.nvidia_timeout_seconds,
        max_retries=settings.nvidia_max_retries,
        additional_kwargs={"top_p": settings.nvidia_top_p, "extra_body": extra_body},
    )


def build_nvidia_llm(settings: Settings) -> Any:
    """Build a LlamaIndex OpenAI-compatible LLM for NVIDIA hosted inference."""
    return _build_openai_like(
        settings,
        model=settings.nvidia_llm_model,
        max_tokens=settings.nvidia_max_tokens,
        enable_thinking=settings.nvidia_enable_thinking,
    )


def build_nvidia_fast_llm(settings: Settings) -> Any | None:
    """Build the optional fast-tier client (ADR-018); ``None`` when not configured.

    The fast tier reuses the same OpenAI-compatible endpoint with a smaller model,
    a tighter output cap, and reasoning disabled — it exists for cheap synthesis
    and degrade-to-fast, not for agent function calling.
    """
    if not settings.model_tier_routing_enabled and not settings.nvidia_fast_llm_model:
        return None
    # When no alternate model is configured, use the primary model with a cheaper
    # synthesis profile (thinking disabled + smaller output cap). This gives direct
    # RAG a bounded fast path without requiring another hosted model.
    model = settings.nvidia_fast_llm_model or settings.nvidia_llm_model
    return _build_openai_like(
        settings,
        model=model,
        max_tokens=settings.nvidia_fast_max_tokens,
        enable_thinking=False,
        configured_context_window=settings.nvidia_fast_context_window,
    )
