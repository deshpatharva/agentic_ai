"""Sliding-window builder for chat messages."""

WINDOW_TURNS = 10


def build_window(
    system_prompt: str,
    history: list,
    *,
    n: int = WINDOW_TURNS,
    context_message: str | None = None,
) -> list[dict]:
    """Return LLM-ready messages[]: system + optional context + last n turns.

    `history` is a list of ORM ChatMessage objects or dicts with .role/.content.
    The system prompt is injected fresh every turn so prompt edits ship without
    touching stored data.

    When a message has .meta with tool_calls, a brief annotation is appended
    to the content so the model knows what actions were taken in prior turns.
    """
    recent = history[-n:] if len(history) > n else history
    window: list[dict] = [{"role": "system", "content": system_prompt}]

    if context_message:
        window.append({"role": "user", "content": context_message})

    for m in recent:
        role = getattr(m, "role", None)
        if role is None:
            role = m["role"]
        content = getattr(m, "content", None)
        if content is None:
            content = m["content"]
        content = content or ""

        meta = getattr(m, "meta", None)
        if meta is None and isinstance(m, dict):
            meta = m.get("meta")

        if meta and isinstance(meta, dict):
            tool_calls = meta.get("tool_calls")
            if tool_calls and isinstance(tool_calls, list):
                annotations = []
                for tc in tool_calls:
                    name = tc.get("name", "unknown")
                    annotations.append(f"[Called {name}]")
                if annotations:
                    content = content + "\n" + " ".join(annotations) if content.strip() else " ".join(annotations)

        window.append({"role": role, "content": content})
    return window
