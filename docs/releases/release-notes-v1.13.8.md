# Release notes — v1.13.8

Released: 2026-09-06

## Input validation (bug fixes)

Eleven new checks catch invalid or dangerous inputs before they reach openLCA, returning clear error messages instead of silent failures or IPC crashes.

- **B01** — `create_flow`, `create_bridge`, `create_process` reject empty or whitespace-only names.
- **B02** — `create_process` rejects an empty exchanges list.
- **B03** — `create_system` verifies the source process has a quantitative reference before building the product system.
- **B04** — `create_process` rejects processes with zero or multiple quantitative references.
- **B05** — `create_process` warns when a unit cannot be resolved to a known flow property.
- **B06** — `create_process` rejects non-numeric exchange amounts and warns on values exceeding 1e15.
- **B07** — `create_system` validates target_amount (positive, below 1e15) and target_unit.
- **B08** — `create_system` detects self-referencing provider links after system creation.
- **B09** — `edit_process` reports which exchange removals, exchange updates, and parameter updates matched nothing.
- **B10** — `scenarios` detects parameter names that do not exist in the product system and filters them out with a warning, instead of passing them silently to the solver.
- **B11** — `create_process` rejects formulas containing dangerous patterns (`exec`, `eval`, `__import__`, `os.`, `subprocess`) and warns on formulas longer than 500 characters.

## Warnings and guardrails

Four new warnings prevent common user mistakes from producing confusing results.

- **W01** — `search_processes` and `search_flows` clamp the search limit to 200 and treat zero or negative limits as the default (20).
- **W02** — `set_database_family` warns when the manually chosen family differs from what auto-detection found, so users know their override may cause naming mismatches.
- **W03** — `sensitivity` rejects variation percentages above 10,000% and warns above 200%.
- **W04** — `create_flow`, `create_bridge`, `create_process` enforce a 250-character name limit; `create_process` enforces a 7-level category depth limit.

## Documentation

- Added `docs/chatgpt.md` — full setup guide for connecting ChatGPT to B280 via the OpenAI Secure MCP Tunnel, covering architecture, installation, security considerations, and troubleshooting.
- Updated README ChatGPT section with architecture diagram, tool annotation reference, and link to the new guide.
- Moved release notes to `docs/releases/`.
- Removed stale `kb_mcp_server.md`.
