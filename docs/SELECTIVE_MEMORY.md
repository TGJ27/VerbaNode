# Selective short-term memory

VerbaNode stores complete conversation history in SQLite, but v0.6.6 no longer sends all history to Ollama on every turn.

## Default behavior

Independent questions are sent with the system prompt, enabled information, and the current user message only. No previous messages or summary are injected.

## When context is selected

Short-term context is selected for explicit recall and clear follow-up requests, including:

- What were we talking about before?
- What did I say earlier?
- What is my name?
- Tell me more.
- Continue.
- What about that project?

## Limits

The selected context contains at most eight previous user/assistant messages plus a compact stored summary. Character budgets reserve context space for policies, tools, information, the current user message, and model output. Empty assistant messages are excluded.

## Empty-output recovery

If Ollama returns HTTP 200 with no content and no tool call, VerbaNode retries once using only a minimal system prompt and the latest user message, with no memory, information, or tools. A second empty result returns a controlled visible fallback.
