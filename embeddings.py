import json
import logging
import math

from openai import AsyncOpenAI

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 1536


async def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a single text."""
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    response = await client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],  # Limit input length
    )
    return response.data[0].embedding


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Get embedding vectors for multiple texts."""
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    # Batch in groups of 20
    all_embeddings = []
    for i in range(0, len(texts), 20):
        batch = [t[:8000] for t in texts[i:i + 20]]
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        all_embeddings.extend([d.embedding for d in response.data])
    return all_embeddings


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_vectors(query_embedding: list[float], stored_vectors: list[dict], top_k: int = 5) -> list[dict]:
    """Search stored vectors by cosine similarity. Returns top-k matches above threshold."""
    results = []
    for vec in stored_vectors:
        embedding = vec["embedding"]
        if isinstance(embedding, str):
            embedding = json.loads(embedding)
        score = cosine_similarity(query_embedding, embedding)
        if score >= 0.3:  # Minimum threshold
            results.append({
                "content": vec["content"],
                "source_type": vec["source_type"],
                "source_id": vec["source_id"],
                "score": round(score, 4),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
