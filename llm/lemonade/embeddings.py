"""Embedding generation via Lemonade's OpenAI-compatible /embeddings
endpoint - same server, same pattern as chat, just a different route.
"""

from typing import Union

import requests

from config import settings


def embed(text: Union[str, list[str]]) -> list[list[float]]:
    """Return one embedding vector per input string, in the same order."""
    payload = {
        "model": settings.EMBEDDING_MODEL,
        "input": text,
    }
    response = requests.post(
        f"{settings.LEMONADE_BASE_URL}/embeddings",
        json=payload,
        timeout=settings.LEMONADE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json()
    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
