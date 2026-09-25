## What's in this release

Input validation hardening and two bug fixes. No new features, no breaking changes. Every previously valid call behaves identically — the only difference is that malformed inputs now get a clear error instead of silently creating bad data.

### Bug fixes

- **Waste bridges were silently broken.** `create_bridge` with `waste=True` was passing the value to the wrong parameter (`provider_flow_id` instead of `waste`), so waste bridges were always created as product bridges. If you've built waste treatment bridges through the MCP, check them — they're wired as products.
- **`edit_process` could remove the quantitative reference exchange**, leaving a process that openLCA can't calculate. Now blocked unless a replacement qref is added in the same call.

### Input validation

- **Category path traversal** (HIGH): `../../etc/passwd` and similar strings rejected in all category fields across `create_flow`, `create_bridge`, `create_process`, `edit_process`, `extract_model`, `create_product_system`.
- **Parameter name validation** (MEDIUM): empty names and non-alphanumeric names (e.g. `import os; os.system('rm -rf /')`) now rejected in `create_process` and `edit_process`.
- **Negative qref amounts** (MEDIUM): `create_process` now rejects negative amounts on quantitative reference exchanges.
- **Formula validation** (MEDIUM): formulas are now checked against openLCA's expression grammar. Code-like strings such as `import('os').system('whoami')` are rejected.
- **UUID validation** (MEDIUM): `provider_id` on `create_bridge` now requires valid UUID format.
- **Limit bounds** (LOW): `search_processes` and `search_flows` return an error for `limit <= 0` instead of silently defaulting to 20.
- **Monte Carlo iterations** (LOW): `monte_carlo` rejects `iterations <= 0`.
- **Empty scenarios** (LOW): `run_scenarios` rejects an empty scenarios dict.

### Schema fix

- `provider_flow_id` added to the `create_bridge` tool schema (was supported by the function but missing from the MCP tool definition).

### Upgrade

```
pip install --upgrade b280-olca-mcp
```
