from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import Field, PrivateAttr

try:
    from llama_index.core.embeddings import BaseEmbedding
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install llama-index-core before importing embeddings") from exc

logger = logging.getLogger(__name__)


class NvidiaNIMEmbedding(BaseEmbedding):
    """LlamaIndex adapter for NVIDIA's OpenAI-compatible embedding endpoint.

    NVIDIA QA/E5 retrieval models distinguish passage embeddings from query
    embeddings. This adapter always sends the correct ``input_type`` and applies
    an explicit truncation policy as a final safety net.
    """

    model_name: str = Field(default="nvidia/nv-embedqa-e5-v5")
    api_base: str = Field(default="https://integrate.api.nvidia.com/v1")
    api_key: str = Field(exclude=True)
    timeout_seconds: float = Field(default=120.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    max_input_tokens: int = Field(default=512, gt=0)
    token_safety_margin: int = Field(default=192, ge=0)
    truncate: Literal["NONE", "START", "END"] = Field(default="END")

    _client: Any = PrivateAttr()
    _aclient: Any = PrivateAttr()

    def __init__(
        self,
        *,
        model_name: str,
        api_base: str,
        api_key: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
        embed_batch_size: int = 16,
        max_input_tokens: int = 512,
        token_safety_margin: int = 192,
        truncate: Literal["NONE", "START", "END"] = "END",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            embed_batch_size=embed_batch_size,
            max_input_tokens=max_input_tokens,
            token_safety_margin=token_safety_margin,
            truncate=truncate,
            **kwargs,
        )
        from openai import AsyncOpenAI, OpenAI

        self._client = OpenAI(
            base_url=api_base,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._aclient = AsyncOpenAI(
            base_url=api_base,
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def safe_input_token_limit(self) -> int:
        return max(1, self.max_input_tokens - self.token_safety_margin)

    def _validate_input_lengths(self, texts: list[str], input_type: str) -> None:
        try:
            from llama_index.core.utils import get_tokenizer

            tokenizer = get_tokenizer()
        except Exception:  # pragma: no cover
            tokenizer = None
        if tokenizer is None:
            return

        safe_limit = self.safe_input_token_limit
        for index, text in enumerate(texts):
            estimated_tokens = len(tokenizer(text))
            if estimated_tokens > safe_limit:
                logger.warning(
                    "embedding_input_exceeds_safe_limit",
                    extra={
                        "input_type": input_type,
                        "input_index": index,
                        "estimated_tokens": estimated_tokens,
                        "safe_limit": safe_limit,
                        "model_limit": self.max_input_tokens,
                        "truncate": self.truncate,
                    },
                )
            if estimated_tokens > self.max_input_tokens and self.truncate == "NONE":
                raise ValueError(
                    f"NVIDIA embedding {input_type} input #{index} is approximately "
                    f"{estimated_tokens} tokens; model limit is {self.max_input_tokens}."
                )

    @staticmethod
    def _ordered_embeddings(response: Any) -> list[list[float]]:
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def _request_body(self, input_type: str) -> dict[str, str]:
        return {"input_type": input_type, "truncate": self.truncate}

    def _embed_sync(self, texts: list[str], input_type: str) -> list[list[float]]:
        self._validate_input_lengths(texts, input_type)
        response = self._client.embeddings.create(
            model=self.model_name,
            input=texts,
            extra_body=self._request_body(input_type),
        )
        return self._ordered_embeddings(response)

    async def _embed_async(self, texts: list[str], input_type: str) -> list[list[float]]:
        self._validate_input_lengths(texts, input_type)
        response = await self._aclient.embeddings.create(
            model=self.model_name,
            input=texts,
            extra_body=self._request_body(input_type),
        )
        return self._ordered_embeddings(response)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed_sync([query], "query")[0]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return (await self._embed_async([query], "query"))[0]

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed_sync([text], "passage")[0]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return (await self._embed_async([text], "passage"))[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._embed_sync(texts, "passage")

    async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_async(texts, "passage")
