from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MemoryContextSelection:
    required: bool
    reason: str
    summary: str | None
    messages: list[dict[str, str]]


_EXPLICIT_MEMORY_PATTERNS = (
    r"\bwhat (?:were|was) we (?:talking|speaking|discussing) about\b",
    r"\bwhat did (?:i|we|you) (?:say|mention|ask|tell)\b",
    r"\bwhat (?:did|have) you remember(?:ed)?\b",
    r"\bdo you remember\b",
    r"\bremember (?:when|what|the|my|our)\b",
    r"\b(?:earlier|before|previously|last time|our previous conversation|the previous conversation)\b",
    r"\bwhat(?:'s| is) my (?:name|preference|project|goal|plan)\b",
    r"\bwhich (?:project|topic|option) (?:was|were) (?:i|we)\b",
    r"\brecap (?:our|the) (?:conversation|discussion|chat)\b",
    r"\bsummarize what we (?:discussed|talked about|decided)\b",
    r"\bcontinue (?:our|the) (?:conversation|discussion|topic)\b",
)

_FOLLOW_UP_PATTERNS = (
    r"^(?:continue|go on|tell me more|explain more|elaborate|why|how so|what else)[?.! ]*$",
    r"^(?:what|how) about (?:that|it|this|the same one)[?.! ]*$",
    r"^(?:can you|could you|please) (?:continue|elaborate|explain that|tell me more)[?.! ]*$",
    r"\b(?:that|this) (?:project|topic|answer|idea|option|problem|one)\b",
    r"\bthe (?:project|topic|option|thing) we (?:discussed|mentioned|talked about)\b",
)


def requires_memory_context(text: str) -> tuple[bool, str]:
    """Return whether a request needs prior conversational context.

    The default is deliberately memory-free. We only inject short-term history
    for explicit recall requests and clear follow-up references.
    """

    normalized = re.sub(r"\s+", " ", str(text or "").casefold()).strip()
    if not normalized:
        return False, "empty"
    if any(re.search(pattern, normalized) for pattern in _EXPLICIT_MEMORY_PATTERNS):
        return True, "explicit_recall"
    if any(re.search(pattern, normalized) for pattern in _FOLLOW_UP_PATTERNS):
        return True, "follow_up_reference"
    return False, "independent_request"


def _clean_message(row: dict[str, Any]) -> dict[str, str] | None:
    role = str(row.get("role") or "").strip()
    content = str(row.get("content") or "").strip()
    if role not in {"user", "assistant"} or not content:
        return None
    return {"role": role, "content": content}


def _trim_messages(messages: list[dict[str, str]], max_chars: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    used = 0
    for message in reversed(messages):
        content = message["content"]
        remaining = max_chars - used
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[-remaining:]
        selected.append({"role": message["role"], "content": content})
        used += len(content)
    selected.reverse()
    return selected


def select_memory_context(
    *,
    text: str,
    summary: str | None,
    prior_messages: list[dict[str, Any]],
    context_size: int,
) -> MemoryContextSelection:
    required, reason = requires_memory_context(text)
    if not required:
        return MemoryContextSelection(False, reason, None, [])

    cleaned = [message for row in prior_messages if (message := _clean_message(row))]
    # Keep short-term context small even when the database contains a long chat.
    # Reserve most of the model context for policies, tools, knowledge, user input,
    # and output. Character counts are used as a conservative, tokenizer-free cap.
    context_size = max(512, int(context_size or 4096))
    total_char_budget = min(6000, max(1800, int(context_size * 1.25)))
    summary_budget = min(2200, total_char_budget // 3)
    history_budget = total_char_budget - summary_budget

    selected_summary = str(summary or "").strip() or None
    if selected_summary and len(selected_summary) > summary_budget:
        selected_summary = selected_summary[:summary_budget].rstrip() + "…"

    # At most eight previous messages are considered, then trimmed to budget.
    selected_messages = _trim_messages(cleaned[-8:], history_budget)
    return MemoryContextSelection(True, reason, selected_summary, selected_messages)
