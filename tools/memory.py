import asyncio
import logging

import db

logger = logging.getLogger(__name__)


async def store_fact(category: str, key: str, value: str, chat_id: int = 0) -> str:
    db.upsert_fact(chat_id, category, key, value)

    # Embed the fact for semantic search (Phase 5)
    try:
        from embeddings import get_embedding
        content = f"[{category}] {key}: {value}"
        embedding = await get_embedding(content)
        db.save_memory_vector(chat_id, "fact", f"{category}:{key}", content, embedding)
    except Exception as e:
        logger.debug(f"Fact embedding skipped: {e}")

    return f"Stored: [{category}] {key} = {value}"


def recall_facts(category: str | None = None, chat_id: int = 0) -> str:
    facts = db.get_facts(chat_id, category)
    if not facts:
        return "No facts stored." if not category else f"No facts in category '{category}'."

    lines = []
    for f in facts:
        lines.append(f"[{f['category']}] {f['key']}: {f['value']}")
    return "\n".join(lines)
