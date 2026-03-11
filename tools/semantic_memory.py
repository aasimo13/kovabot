import logging

import db
from embeddings import get_embedding, search_vectors

logger = logging.getLogger(__name__)


async def semantic_recall(query: str, top_k: int = 5, chat_id: int = 0) -> str:
    """Search long-term memory by semantic similarity/meaning."""
    try:
        query_embedding = await get_embedding(query)
        stored = db.get_memory_vectors(chat_id)

        if not stored:
            return "No semantic memories stored yet."

        results = search_vectors(query_embedding, stored, top_k=top_k)

        if not results:
            return f"No relevant memories found for: {query}"

        lines = []
        for r in results:
            source_label = f"[{r['source_type']}]"
            lines.append(f"- {source_label} {r['content']} (relevance: {r['score']})")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"semantic_recall error: {e}")
        return f"Error in semantic recall: {e}"
