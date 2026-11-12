# Release notes: v2.0.0

Prepared 12/11/2026. Not yet released.

Version 2.0 turns the package inside out. Up to 1.16 the engine that talks to openLCA lived here and olcaBASIC depended on it. Now the engine lives in olcaBASIC, and this server is a thin layer that runs olcaBASIC programs. The reason is enforcement: 1.16 shipped about 550 lines of instructions telling the assistant what not to do, and an assistant can ignore instructions. A language cannot be talked out of a refusal.

Since the first draft of this release, olcaBASIC 0.4.0 has grown to reach every method of openLCA's IPC server, 17 of its 18 entity types and every field of a process, and the remaining ways of building a model wrongly without an error have become errors. This server passes all of it through: see "What the assistant can now do" and the second half of the behaviour table.

Needs olcaBASIC 0.4.0 and Python 3.11 or later. [MIGRATION.md](../MIGRATION.md) covers the move for people who call the old tools or import `LCAFunctions`.

## Three tools

| Tool | Purpose |
|---|---|
| `olcabasic_run` | Run an olcaBASIC program (`code`), or check it without touching openLCA (`dry_run`). Returns `ok`, `text`, `data` (the structured result of every command, `RESULT` queries included, in the shape `olcabasic.Session` gives Python), `errors`, `warnings` |
| `olcabasic_help` | The command reference: overview, a topic, or one command. Generated from the same registry as olcaBASIC's `HELP` |
| `olcabasic_reset` | Clear the session's variables, scenarios and active EPD. The database is not touched |

One session lasts as long as the server: variables, the current folder, scenarios and the latest results carry over between calls. Calls run one at a time, so product systems are never created in parallel.

The server starts without openLCA. The first call that needs it connects, and says what to do if it cannot.

## Two flags, both off by default

- `OLCA_MCP_LEGACY_TOOLS=1` brings back the 36 typed tools of version 1. They call the engine directly and skip every rule the language enforces; each tool's description now starts by saying so.
- `OLCA_MCP_ALLOW_PYTHON=1` adds `python_exec`, for what olcaBASIC cannot express. It skips every rule too, and its description says so. It runs Python in the server process with `session`, `engine` and `client` in scope, under the same lock, with a time limit. Every call must give a `why_not_basic` reason and is logged to `~/.olcabasic/python_log.jsonl`.

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
| Parameterising a database process | The instructions asked the assistant to warn about backups first | `PARAMETERISE PROCESS "name" CONFIRM`: refused without `CONFIRM`, and the refusal says how many amounts would change and to back up first | Back up the database, then add `CONFIRM`. `ALL` (elementary flows too) asks twice at the olcaBASIC terminal and is refused through the MCP |
| EPD modelling | Seven steps of advice in the instructions | Commands that refuse a wrong module set, a wrong method, a background process used directly, and a programme rule that is broken | See "EPDs" below |
| A background process used straight in a process | The instructions asked for bridges in EPD models | Error everywhere, with the bridge to write. No opt-out | `BRIDGE "Cement", kg` / `PROVIDER "name" LOCATION "code"` / `END BRIDGE`, then `INPUT USE PROCESS "BRIDGE \| Cement \| kg", ...` |
| A `MAKE PROCESS` block sent again after it was changed | The old process stayed, with a warning the assistant could miss | Error listing the differences. An identical block is still a quiet no-op | `EDIT PROCESS "name" ... END EDIT`, or `DELETE PROCESS` and build again |
| Calculating after a process was edited, linked, moved or parameterised | Allowed: the product system kept its old links | Refused until the system is built again and passes `VALIDATE` | `DELETE SYSTEM`, `SYSTEM`, `VALIDATE` |
| One EPD module using another module's process | Warning; counted twice | Error | Give the module its own input |
| `OUTPUT "name"` that matches no flow | Created the flow, with a note | Error | `OUTPUT MAKE FLOW "name", ...` |
| A new emission the method has no factor for | Added zero without a word | Every calculation refused, naming the flow | Use a flow the method knows, or `CALCULATE ... IGNORE FACTORS "flow"` once the user agrees |
| Monte Carlo on a model with no uncertainty | Ran, and said every run was the same | Error before the runs start | `UNCERTAINTY ...` on the uncertain lines |
| `ALLOCATE PHYSICAL` or `ECONOMIC` with no factors on a multi-product process | Calculated without sharing anything out | Error naming the process | `ALLOCATION ... END ALLOCATION` in the process, or `ALLOCATE NONE` |
| Changing an impact method olcaBASIC did not make | Possible through the typed tools | Refused through the MCP: it needs a person at the olcaBASIC terminal | Make a method of your own with `MAKE METHOD` |
| A reply that is too long | The structured data was dropped | Tables are cut to their first 50 rows first (`rows_omitted`); the data is only dropped if that is not enough | Ask for less: `TOP n`, a `CATEGORY`, or `SAVE "file.csv"` |
| `from b280_olca_mcp.functions import LCAFunctions` | The engine | A shim: works, with a `DeprecationWarning` | `from olcabasic.engine import Engine` |
| Dependencies | `mcp`, `olca-ipc` | `mcp`, `olcabasic` (which brings `olca-ipc`) | `pip install --upgrade b280-olca-mcp` |
| Python | 3.10 declared (3.11 needed in practice) | 3.11 declared | Use 3.11 or later |
| Instructions resource | About 550 lines | 144 lines: how to talk to the user and present results. The rules are in the language, and the instructions say there is no way round a refusal | Nothing |

The legacy tools, when switched on, behave as they did in 1.16: none of the changes in this table applies to them.

## What the assistant can now do

Everything olcaBASIC 0.4.0 can, through `olcabasic_run`:

- **Read more from a result.** `CALCULATE` leaves its result open and `RESULT` queries it: contributions by process and by elementary flow, where one emission comes from, characterisation factors, intensities, scaling factors, total requirements, upstream trees, costs, normalised and weighted results, results by analysis group, Sankey data. Each query comes back as structured data. A result stays open between calls and is disposed on `olcabasic_reset`.
- **Write every field of a process.** Uncertainty distributions, avoided products, costs, allocation factors, the 26 documentation fields, social aspects, process type; parameter sets and analysis groups on product systems.
- **Work with every entity type.** `FIND`, `SHOW` (also as JSON-LD and with where it is used), `DELETE` and `MOVE` for actors, sources, currencies, locations, unit groups, flow properties, social indicators, data quality systems, impact methods, projects, stored results and EPDs, and `MAKE` blocks for most of them.
- **Finish an EPD in openLCA.** `EPD SAVE`, representativeness ratings and the data quality register and table, biogenic carbon balances, group sensitivity, the model written out for a verifier.

`olcabasic_help` covers all of it from olcaBASIC's command registry (133 commands); the overview is about 1,050 tokens.

## EPDs

EPDs to EN 15804+A2 are now olcaBASIC commands (olcaBASIC 0.4.0): `EPD ... END EPD`, `MODULE ... TOTAL ... END MODULE`, `EPD SYSTEMS`, `EPD CHECK`, `EPD CALCULATE`, `EPD DATA QUALITY`, `EPD REPORT`. The standard's module rules are checked as the EPD block is read. With `PROGRAMME "IES"` the rules of the International EPD System (General Programme Instructions 5.1.0, Annex A) apply as errors with no override: data declarations on every process and bridge, the electricity hierarchy, sub-national grids, cut-off limits, proxy data limits and data age.

What stays a conversation is deciding which item of the inventory belongs in which module. The instructions keep that step and nothing else of the old workflow.

## Smaller things

- Replies above 60,000 characters are cut, and say so.
- The server reports its own version to the client (it reported the MCP library's default before).
- `tests/`: 152 offline tests, including the version 1 server tests run with the legacy flag on and the shortcut suite (`tests/test_shortcuts.py`): 26 programs that each try one way round a rule, sent through `olcabasic_run`, each refused with a line and a hint and the database unchanged. They run against a fake openLCA client, so no database is needed.
