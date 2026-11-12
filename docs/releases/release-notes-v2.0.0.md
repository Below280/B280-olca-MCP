# Release notes: v2.0.0

Prepared 12/11/2026. Not yet released.

Version 2.0 turns the package inside out. Up to 1.16 the engine that talks to openLCA lived here and olcaBASIC depended on it. Now the engine lives in olcaBASIC, and this server is a thin layer that runs olcaBASIC programs. The reason is enforcement: 1.16 shipped about 550 lines of instructions telling the assistant what not to do, and an assistant can ignore instructions. A language cannot be talked out of a refusal.

Needs olcaBASIC 0.4.0 and Python 3.11 or later. [MIGRATION.md](../MIGRATION.md) covers the move for people who call the old tools or import `LCAFunctions`.

## Three tools

| Tool | Purpose |
|---|---|
| `olcabasic_run` | Run an olcaBASIC program (`code`), or check it without touching openLCA (`dry_run`). Returns `ok`, `text`, `data`, `errors`, `warnings` |
| `olcabasic_help` | The command reference: overview, a topic, or one command. Generated from the same registry as olcaBASIC's `HELP` |
| `olcabasic_reset` | Clear the session's variables, scenarios and active EPD. The database is not touched |

One session lasts as long as the server: variables, the current folder, scenarios and the latest results carry over between calls. Calls run one at a time, so product systems are never created in parallel.

The server starts without openLCA. The first call that needs it connects, and says what to do if it cannot.

## Two flags, both off by default

- `OLCA_MCP_LEGACY_TOOLS=1` brings back the 36 typed tools of version 1, unchanged.
- `OLCA_MCP_ALLOW_PYTHON=1` adds `python_exec`, for what olcaBASIC cannot express. It runs Python in the server process with `session`, `engine` and `client` in scope, under the same lock, with a time limit. Every call must give a `why_not_basic` reason and is logged to `~/.olcabasic/python_log.jsonl`.

## Behaviour changes

Each of these used to pass quietly, or depended on the assistant following its instructions. Each is now an error from the language, with the line and what to type instead.

| Change | 1.16 | 2.0 | What to do |
|---|---|---|---|
| Tools | 36 typed tools | `olcabasic_run`, `olcabasic_help`, `olcabasic_reset` | Nothing if you chat with an assistant. For clients written against the old tools: `OLCA_MCP_LEGACY_TOOLS=1`, or move to `olcabasic_run` ([MIGRATION.md](../MIGRATION.md)) |
| A process name that matches several processes | The instructions asked the assistant not to choose; the tool took the first | Error listing the location and UUID of each | Add `LOCATION "code"` to the line, or `PROVIDER "uuid"` |
| Impact method names | Part of a name was enough if it matched one method | The full name is required; a near miss lists the close matches | Use the full name (`"EF v3.1"`, not `"EF"`). `FIND METHOD "text"` lists them |
| Building before the database family is known | Went ahead with ecoinvent flow property names | Refused | `DATABASE FAMILY "ecoinvent"` or `"flcac"` (normally detected on connect) |
| Calculating a system that failed validation | Allowed | Refused for the rest of the session, until `VALIDATE` passes | Fix the links, or delete and rebuild the system, then `VALIDATE` |
| Sensitivity without a range | Varied by 20% | Parse error | Say the range: `BY 10%` |
| Tier 1 model check | The instructions asked the assistant not to present it as proof | The output always ends by saying it checked structure only | Nothing |
| Defaults (allocation, linking, top n, runs) | Applied silently | Stated in the output the first time each is used | Nothing |
| EPD modelling | Seven steps of advice in the instructions | Commands that refuse a wrong module set, a wrong method, a background process used directly, and a programme rule that is broken | See "EPDs" below |
| `from b280_olca_mcp.functions import LCAFunctions` | The engine | A shim: works, with a `DeprecationWarning` | `from olcabasic.engine import Engine` |
| Dependencies | `mcp`, `olca-ipc` | `mcp`, `olcabasic` (which brings `olca-ipc`) | `pip install --upgrade b280-olca-mcp` |
| Python | 3.10 declared (3.11 needed in practice) | 3.11 declared | Use 3.11 or later |
| Instructions resource | About 550 lines | 148 lines: how to talk to the user and present results. The rules are in the language | Nothing |

The legacy tools, when switched on, behave as they did in 1.16: none of the changes in this table applies to them.

## EPDs

EPDs to EN 15804+A2 are now olcaBASIC commands (olcaBASIC 0.4.0): `EPD ... END EPD`, `MODULE ... TOTAL ... END MODULE`, `EPD SYSTEMS`, `EPD CHECK`, `EPD CALCULATE`, `EPD DATA QUALITY`, `EPD REPORT`. The standard's module rules are checked as the EPD block is read. With `PROGRAMME "IES"` the rules of the International EPD System (General Programme Instructions 5.1.0, Annex A) apply as errors with no override: data declarations on every process and bridge, the electricity hierarchy, sub-national grids, cut-off limits, proxy data limits and data age.

What stays a conversation is deciding which item of the inventory belongs in which module. The instructions keep that step and nothing else of the old workflow.

## Smaller things

- Replies above 60,000 characters are cut, and say so.
- The server reports its own version to the client (it reported the MCP library's default before).
- `tests/`: 67 offline tests, including the version 1 server tests run with the legacy flag on. They run against a fake openLCA client, so no database is needed.

## Not in this release

- `PARAMETERISE PROCESS` (turning the fixed amounts of a database process into parameters) is not a command yet. With the legacy tools on, `edit_process` still does it.
