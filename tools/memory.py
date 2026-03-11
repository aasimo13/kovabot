import db


def store_fact(category: str, key: str, value: str, chat_id: int = 0) -> str:
    db.upsert_fact(chat_id, category, key, value)
    return f"Stored: [{category}] {key} = {value}"


def recall_facts(category: str | None = None, chat_id: int = 0) -> str:
    facts = db.get_facts(chat_id, category)
    if not facts:
        return "No facts stored." if not category else f"No facts in category '{category}'."

    lines = []
    for f in facts:
        lines.append(f"[{f['category']}] {f['key']}: {f['value']}")
    return "\n".join(lines)
