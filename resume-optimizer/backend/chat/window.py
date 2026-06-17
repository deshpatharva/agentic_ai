"""Sliding-window builder for Groq messages[]."""

WINDOW_TURNS = 10  # last N user/assistant turns included in each API call


def build_window(system_prompt: str, history: list, *, n: int = WINDOW_TURNS) -> list[dict]:
    """Return Groq-ready messages[]: pinned system prompt + last n stored turns.

    `history` is a list of ORM ChatMessage objects or dicts with .role/.content.
    The system prompt is injected fresh every turn so prompt edits ship without
    touching stored data.
    """
    recent = history[-n:] if len(history) > n else history
    window: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in recent:
        role = getattr(m, "role", None)
        if role is None:
            role = m["role"]
        content = getattr(m, "content", None)
        if content is None:
            content = m["content"]
        window.append({"role": role, "content": content or ""})
    return window
