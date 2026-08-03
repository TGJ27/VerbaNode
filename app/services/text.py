from __future__ import annotations

import re

# Backend output guard. The prompt asks the model not to emit emoji, while this
# sanitizer enforces the rule for chat, memory, generated greetings, and TTS.
# Ranges intentionally target emoji/pictographs rather than general non-ASCII
# text, so normal multilingual output remains available.
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # regional indicator flags
    "\U0001F300-\U0001F5FF"  # symbols and pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport and map
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # geometric extended
    "\U0001F800-\U0001F8FF"  # arrows extended
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FAFF"  # symbols extended
    "\U00002600-\U000026FF"  # miscellaneous symbols
    "\U00002700-\U000027BF"  # dingbats
    "]+",
    flags=re.UNICODE,
)
_KEYCAP_RE = re.compile(r"[0-9#*]\ufe0f?\u20e3")
_EMOJI_MODIFIER_RE = re.compile(r"[\U0001F3FB-\U0001F3FF]")
_EMOJI_JOINER_RE = re.compile(r"[\u200d\ufe0e\ufe0f\u20e3]")
_EMOTICON_RE = re.compile(
    r"(?:(?<=^)|(?<=\s))(?:[:;=8xX][-^'oO*]?[)(/\\DPpOo]|<3)(?=$|\s|[.!?,])"
)
_SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?])")
_HORIZONTAL_SPACE_RE = re.compile(r"[ \t]{2,}")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")


def strip_emoji(text: str) -> str:
    """Remove emoji, pictographs, joiners, modifiers, keycaps, and emoticons."""

    value = str(text or "")
    value = _KEYCAP_RE.sub("", value)
    value = _EMOJI_RE.sub("", value)
    value = _EMOJI_MODIFIER_RE.sub("", value)
    value = _EMOJI_JOINER_RE.sub("", value)
    value = _EMOTICON_RE.sub("", value)
    return value


def clean_assistant_text(text: str) -> str:
    """Return stable user-visible and TTS-safe assistant text."""

    value = strip_emoji(text).replace("\r\n", "\n").replace("\r", "\n")
    value = _SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", value)
    value = _HORIZONTAL_SPACE_RE.sub(" ", value)
    value = _EXCESS_BLANK_LINES_RE.sub("\n\n", value)
    return value.strip()
