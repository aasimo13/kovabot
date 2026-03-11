async def think(thought: str, chat_id: int = 0) -> str:
    """Internal reasoning tool. The model uses this to think through
    a problem before taking action. Returns the thought back so the
    model can build on it."""
    return f"Thought noted. Now act on it."
