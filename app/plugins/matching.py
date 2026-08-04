from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    value = text.casefold().replace("’", "'")
    value = re.sub(r"[^\w\s'?-]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip(" ?-")


def strip_conversational_wrappers(text: str) -> str:
    """Remove greetings, wake words, and politeness wrappers before routing."""
    value = text.strip()
    leading_patterns = (
        r"^(?:hello|hi|hey|yo|halo|hai)\b\s*",
        r"^good (?:morning|afternoon|evening)\b\s*",
        r"^(?:excuse me|permisi)\b\s*",
        r"^(?:ropi|assistant)\b\s*",
        r"^(?:please|pls|tolong)\b\s*",
    )
    changed = True
    while changed and value:
        changed = False
        for pattern in leading_patterns:
            updated = re.sub(pattern, "", value, count=1).strip()
            if updated != value:
                value = updated
                changed = True
                break

    trailing_patterns = (
        r"\s+(?:please|pls|tolong)$",
        r"\s+(?:thanks|thank you|makasih|terima kasih)$",
        r"\s+(?:for me|right now|now please)$",
    )
    changed = True
    while changed and value:
        changed = False
        for pattern in trailing_patterns:
            updated = re.sub(pattern, "", value, count=1).strip()
            if updated != value:
                value = updated
                changed = True
                break
    return value


def normalized_core(text: str) -> str:
    return strip_conversational_wrappers(normalize_text(text))


def tokens_fit(text: str, *, required: set[str], allowed: set[str]) -> bool:
    tokens = [token.replace("'", "") for token in text.split() if token]
    token_set = set(tokens)
    return bool(tokens) and required.issubset(token_set) and token_set.issubset(allowed)
