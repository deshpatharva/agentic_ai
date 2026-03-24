"""
Token budget utilities — rough word-based truncation.
1 token ≈ 0.75 words (conservative estimate).
"""


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens tokens by word count."""
    words = text.split()
    max_words = int(max_tokens * 0.75)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])
