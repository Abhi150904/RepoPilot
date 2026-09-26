from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text."""


class HashEmbeddingProvider:
    """Deterministic local embedding provider for tests and offline development."""

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive.")
        self._dimensions = dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize(_hash_embed(text, self._dimensions)) for text in texts]


def tokenize_for_embedding(text: str) -> list[str]:
    expanded = _split_camel_case(text)
    raw_tokens = re.findall(r"[a-z][a-z0-9]+", expanded.lower())
    tokens = [_normalize_token(token) for token in raw_tokens if len(token) > 1]
    return _dedupe(tokens)


def _hash_embed(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for token in tokenize_for_embedding(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return vector


def _normalize(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _split_camel_case(text: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)


def _normalize_token(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return unique_items
