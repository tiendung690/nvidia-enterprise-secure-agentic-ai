from __future__ import annotations

from typing import Any

from nvidia_agentic_rag.nvidia.errors import ProviderErrorInfo, classify_provider_error

__all__ = [
    "NvidiaNIMEmbedding",
    "ProviderErrorInfo",
    "build_nvidia_fast_llm",
    "build_nvidia_llm",
    "classify_provider_error",
]


def __getattr__(name: str) -> Any:
    if name == "NvidiaNIMEmbedding":
        from nvidia_agentic_rag.nvidia.embeddings import NvidiaNIMEmbedding

        return NvidiaNIMEmbedding
    if name == "build_nvidia_llm":
        from nvidia_agentic_rag.nvidia.llm import build_nvidia_llm

        return build_nvidia_llm
    if name == "build_nvidia_fast_llm":
        from nvidia_agentic_rag.nvidia.llm import build_nvidia_fast_llm

        return build_nvidia_fast_llm
    raise AttributeError(name)
