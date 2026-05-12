"""
Embedding client for ZoomMind using MiniMax API.

Provides semantic embeddings for nodes and queries to enable
embedding-based matching instead of pure keyword matching.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "emb-01"
_EMBEDDING_DIM = 1536


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _get_embedding_config() -> dict[str, Any]:
    _load_dotenv_if_available()
    base_url = os.getenv("ZOOMMIND_LLM_BASE_URL", "https://api.minimax.chat/v1").rstrip("/")
    api_key = os.getenv("ZOOMMIND_LLM_API_KEY", "")

    if not api_key:
        logger.warning("ZOOMMIND_LLM_API_KEY not set - embedding will use fallback")

    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": _EMBEDDING_MODEL,
        "dimension": _EMBEDDING_DIM,
    }


# MiniMax embedding endpoint uses "texts" not "input"
_EMBEDDING_PAYLOAD_KEY = "texts"


def is_embedding_available() -> bool:
    config = _get_embedding_config()
    return bool(config["api_key"])


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """
    Embed a batch of texts using MiniMax embedding API.

    Returns list of embedding vectors (or None if failed) aligned with input texts.
    Uses trust_env=False to bypass system proxy.
    """
    config = _get_embedding_config()
    if not config["api_key"]:
        logger.warning("Embedding API unavailable (no API key)")
        return [None] * len(texts)

    if not texts:
        return []

    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": config["model"],
        "texts": texts,
    }

    try:
        with httpx.Client(timeout=60.0, trust_env=False) as client:
            response = client.post(
                f"{config['base_url']}/embeddings",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "Embedding API failed (%s), falling back to None embeddings: %s",
            type(exc).__name__,
            exc,
        )
        return [None] * len(texts)

    data = response.json()
    try:
        embeddings = data["data"]
        results: list[list[float] | None] = [None] * len(texts)
        for item in embeddings:
            idx = item.get("index")
            vector = item.get("embedding")
            if idx is not None and vector is not None:
                results[idx] = vector
        return results
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Failed to parse embedding response: %s", exc)
        return [None] * len(texts)


def embed_text(text: str) -> list[float] | None:
    """Embed a single text. Returns None if API unavailable."""
    results = embed_texts([text])
    return results[0] if results else None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(y * y for y in b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def embedding_to_json(embedding: list[float]) -> str:
    """Serialize embedding vector to JSON string for database storage."""
    return json.dumps(embedding)


def json_to_embedding(json_str: str | None) -> list[float] | None:
    """Deserialize embedding vector from JSON string."""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return None