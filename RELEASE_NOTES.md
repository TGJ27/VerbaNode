# VerbaNode v0.5.1 Phase 3 UI and STT Display Test Release

This test build improves dashboard organization without changing the v0.5.0 Core, Audio Engine, or AI Engine process boundaries.

## Highlights

- Settings is now divided into five focused submenus: Conversation, Host audio, AI models, Runtime, and Data.
- Desktop uses a compact category sidebar; phone layouts use a swipeable horizontal category bar.
- Added a persistent **Show rejected STT transcripts** toggle under Conversation settings.
- Low-confidence speech remains blocked from the agent when confidence filtering is enabled.
- Rejected transcripts are shown as muted gray diagnostic messages instead of normal blue user messages.
- When display is disabled, future rejected transcripts are not inserted into the visible chat.
- Existing database, agents, conversations, models, audio settings, tools, memory, and process-isolation behavior remain compatible.
- 64 automated tests pass.

## Validation required

Test the toggle in both states, switch through every Settings submenu on desktop and phone, and confirm that accepted STT, rejected STT, Audio Engine controls, AI Engine controls, model management, and backup/restore remain functional.
