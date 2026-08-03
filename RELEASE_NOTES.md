# VerbaNode v0.3.3 Release Notes


## Highlights
- Fixes current time/date requests being answered by the LLM when users include greetings or natural filler.
- “Hello, what time is it?”, “Hey Ropi, tell me the time right now”, and similar phrases now execute get_current_time directly.
- Minor ASR/typing errors such as “what day its its?” are recognized as current date/time requests.
- Greeting handling also applies to current location, live weather, and stop-conversation commands.
- Conservative exclusions keep time complexity, response-time, travel-time, meeting-time, and timezone questions with the LLM.
- Direct time output uses VERBANODE_DEFAULT_TIMEZONE (Asia/Jakarta by default).

## Expected log for a successful direct route
Deterministic core tool route: intent=get_current_time text='hello what time is it?'

## Upgrade
Keep your existing .git, .env, data, models, and certs directories. Copy the new repository files over the existing checkout, then run setup_database.bat and run.bat. No database migration is required for this patch.

## Repository cleanup

- Removed device-brand-specific guidance from the dashboard.
- Historical release changes remain in `CHANGELOG.md`.
- This file is replaced for each new release instead of creating another versioned release-note file.
